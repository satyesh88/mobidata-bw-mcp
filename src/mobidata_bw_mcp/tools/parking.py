import re
from typing import Any, Literal

from ..clients import geocode, parkapi
from ..config import DATASET_LICENSES, settings
from ..geo import compact_dict, haversine_m
from ..models import LocationInput, ResultEnvelope, source_info
from .common import freshness, latest_datetime, limit_value

_GENERIC_NAME_WORDS = {
    "am",
    "cityparkhaus",
    "heilbronn",
    "parkhaus",
    "parkplatz",
    "quartiersgarage",
}


def _name_tokens(name: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9äöüß]+", (name or "").casefold())
        if token not in _GENERIC_NAME_WORDS
    }


def _deduplicate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    removed = 0
    for record in records:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if record.get("capacity") == existing.get("capacity")
                and _name_tokens(record.get("name")) & _name_tokens(existing.get("name"))
                and haversine_m(
                    record["lat"], record["lon"], existing["lat"], existing["lon"]
                )
                <= 200
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(record)
            continue
        removed += 1
        existing = kept[duplicate_index]
        if bool(record.get("has_realtime_data")) > bool(existing.get("has_realtime_data")):
            kept[duplicate_index] = record
    return kept, removed


async def find_parking(
    location: LocationInput | dict[str, Any],
    radius_m: int = 1000,
    purpose: Literal["CAR", "BIKE", "MOTORCYCLE", "ITEM"] = "CAR",
    only_free: bool = False,
    truck: bool = False,
    limit: int = 20,
    cursor: int | None = None,
) -> dict[str, Any]:
    """Find the nearest parking with live capacity. Use next_cursor for further results.

    purpose: CAR (default), BIKE for bicycle stands/lockers, MOTORCYCLE, ITEM for bike boxes.
    """
    bounded_limit = limit_value(limit)
    if cursor is not None and cursor < 0:
        raise ValueError("cursor must not be negative")
    resolved = await geocode.resolve(location)
    records, searched_radius = await parkapi.nearest_parking_sites(
        {"lat": resolved.lat, "lon": resolved.lon, "purpose": purpose}, radius_m
    )
    records, duplicates_removed = _deduplicate(records)
    items = []
    for record in records:
        free = record.get("realtime_free_capacity_truck" if truck else "realtime_free_capacity")
        capacity = record.get("capacity_truck" if truck else "capacity")
        if truck and not (record.get("capacity_truck") or 0) > 0:
            continue
        if only_free and not (free or 0) > 0:
            continue
        item = compact_dict(
            {
                "id": record.get("id"),
                "name": record.get("name"),
                "type": record.get("type"),
                "address": record.get("address"),
                "capacity": capacity,
                "free_now": free,
                "max_height_m": (
                    record.get("max_height") / 100 if record.get("max_height") else None
                ),
                "lat": record.get("lat"),
                "lon": record.get("lon"),
                "distance_m": round(
                    haversine_m(resolved.lat, resolved.lon, record["lat"], record["lon"])
                ),
                **freshness(
                    record.get("realtime_data_updated_at"),
                    live_available=bool(record.get("has_realtime_data")),
                ),
            }
        )
        items.append(item)
    items.sort(key=lambda item: item["distance_m"])
    start = cursor or 0
    total_matches = len(items)
    items = items[start : start + bounded_limit]
    next_cursor = start + bounded_limit if start + bounded_limit < total_matches else None
    stale = sum(not item.get("is_live", False) for item in items)
    warnings = []
    if purpose == "MOTORCYCLE":
        warnings.append("Motorcycle parking is published by very few sources; results are sparse")
    if stale:
        warnings.append(f"{stale} of {len(items)} sites do not have current live data")
    if duplicates_removed:
        warnings.append(f"Removed {duplicates_removed} duplicate parking sites")
    if searched_radius < radius_m:
        warnings.append(
            f"Dense area: only the nearest {searched_radius} m of the requested "
            f"{radius_m} m were searched; results are still nearest-first"
        )
    if next_cursor is not None:
        warnings.append(
            f"Results are truncated; request the next page with cursor={next_cursor}"
        )
    for item in items:
        if item.get("free_now", 0) > item.get("capacity", float("inf")):
            warnings.append(
                f"{item.get('name', item.get('id'))}: reported free spaces "
                f"({item['free_now']}) exceed capacity ({item['capacity']})"
            )
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True),
            "radius_m": radius_m,
            "purpose": purpose,
            "only_free": only_free,
            "truck": truck,
            "limit": bounded_limit,
            "cursor": cursor,
        },
        count=len(items),
        truncated=next_cursor is not None,
        next_cursor=next_cursor,
        items=items,
        source=source_info(
            "gebuendelte-parkdaten-bw",
            f"{settings.parkapi_url}parking-sites",
            DATASET_LICENSES["parking"],
        ),
        data_timestamp=latest_datetime([item.get("updated_at") for item in items]),
        warnings=warnings,
    ).compact()