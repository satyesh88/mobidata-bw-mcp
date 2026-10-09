import re
from typing import Any

from ..clients import geocode, parkapi
from ..config import DATASET_LICENSES, settings
from ..geo import compact_dict, haversine_m
from ..models import LocationInput, ResultEnvelope, source_info
from .common import freshness, latest_datetime

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
    purpose: str = "CAR",
    only_free: bool = False,
    truck: bool = False,
) -> dict[str, Any]:
    """Find nearby parking with live capacity; truck mode requires truck spaces."""
    resolved = await geocode.resolve(location)
    records, total = await parkapi.parking_sites(
        {"lat": resolved.lat, "lon": resolved.lon, "radius": radius_m, "purpose": purpose},
        settings.max_limit,
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
    stale = sum(not item.get("is_live", False) for item in items)
    warnings = []
    if stale:
        warnings.append(f"{stale} of {len(items)} sites do not have current live data")
    if duplicates_removed:
        warnings.append(f"Removed {duplicates_removed} duplicate parking sites")
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
        },
        count=len(items),
        truncated=total > len(records),
        items=items,
        source=source_info(
            "gebuendelte-parkdaten-bw",
            f"{settings.parkapi_url}parking-sites",
            DATASET_LICENSES["parking"],
        ),
        data_timestamp=latest_datetime(
            [record.get("realtime_data_updated_at") for record in records]
        ),
        warnings=warnings,
    ).compact()