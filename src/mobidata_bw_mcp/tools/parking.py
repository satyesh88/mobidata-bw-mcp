from typing import Any

from ..clients import geocode, parkapi
from ..config import DATASET_LICENSES, settings
from ..geo import compact_dict, haversine_m
from ..models import LocationInput, ResultEnvelope, source_info
from .common import freshness, latest_datetime


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
        warnings=[f"{stale} of {len(items)} sites do not have current live data"] if stale else [],
    ).compact()