from typing import Any

from ..clients import geocode, wfs
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict, geometry_location, haversine_m
from ..models import LocationInput, ResultEnvelope, source_info
from .common import freshness, latest_datetime


async def find_charging(
    location: LocationInput | dict[str, Any],
    radius_m: int = 2000,
    min_power_kw: float = 0,
    only_available: bool = False,
) -> dict[str, Any]:
    """Find nearby charge locations, filtering by maximum power and live connector availability."""
    resolved = await geocode.resolve(location)
    payload = await wfs.features(
        "MobiData-BW:charge_points", bbox=bbox_around(resolved, radius_m), limit=1000
    )
    items = []
    for feature in payload.get("features", []):
        props = feature["properties"]
        lat, lon = geometry_location(feature["geometry"])
        distance = haversine_m(resolved.lat, resolved.lon, lat, lon)
        power_kw = (props.get("max_electric_power") or 0) / 1000
        available = props.get("chargepoint_available_count")
        if distance > radius_m or power_kw < min_power_kw:
            continue
        if only_available and not (available or 0) > 0:
            continue
        items.append(
            compact_dict(
                {
                    "id": props.get("id"),
                    "name": props.get("name") or props.get("address"),
                    "operator": props.get("operator_name"),
                    "address": props.get("address"),
                    "city": props.get("city"),
                    "max_power_kw": power_kw,
                    "available": available,
                    "total": props.get("chargepoint_static_count"),
                    "charging": props.get("chargepoint_charging_count"),
                    "out_of_order": props.get("chargepoint_outoforder_count"),
                    "lat": lat,
                    "lon": lon,
                    "distance_m": round(distance),
                    **freshness(
                        props.get("status_last_updated"),
                        outdated=props.get("realtime_data_outdated"),
                        live_available=props.get("status_last_updated") is not None,
                    ),
                }
            )
        )
    items.sort(key=lambda item: item["distance_m"])
    stale = sum(not item.get("is_live", False) for item in items)
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True),
            "radius_m": radius_m,
            "min_power_kw": min_power_kw,
            "only_available": only_available,
        },
        count=len(items),
        items=items,
        source=source_info("charge_points", settings.wfs_url, DATASET_LICENSES["wfs"]),
        data_timestamp=latest_datetime([item.get("updated_at") for item in items]),
        warnings=[f"{stale} of {len(items)} locations lack current status data"] if stale else [],
    ).compact()