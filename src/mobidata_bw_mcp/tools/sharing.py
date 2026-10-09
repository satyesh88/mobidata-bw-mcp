from typing import Any

from ..clients import geocode, wfs
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict, geometry_location, haversine_m
from ..models import LocationInput, ResultEnvelope, source_info
from .common import freshness, latest_datetime

KIND_FIELDS = {
    "bicycle": "num_bicycles_available",
    "car": "num_cars_available",
    "scooter": "num_scooters_available",
    "cargo_bicycle": "num_cargo_bicycles_available",
    "moped": "num_mopeds_available",
}


async def find_sharing(
    location: LocationInput | dict[str, Any], radius_m: int = 500, kind: str = "any"
) -> dict[str, Any]:
    """Find live sharing stations and free-floating vehicles, counts, and range."""
    if kind != "any" and kind not in KIND_FIELDS:
        raise ValueError(f"kind must be any or one of: {', '.join(KIND_FIELDS)}")
    resolved = await geocode.resolve(location)
    bbox = bbox_around(resolved, radius_m)
    stations, vehicles = await __import__("asyncio").gather(
        wfs.features("MobiData-BW:sharing_stations", bbox=bbox, limit=1000),
        wfs.features("MobiData-BW:sharing_vehicles", bbox=bbox, limit=1000),
    )
    items = []
    for item_type, payload in (("station", stations), ("vehicle", vehicles)):
        for feature in payload.get("features", []):
            props = feature["properties"]
            lat, lon = geometry_location(feature["geometry"])
            distance = haversine_m(resolved.lat, resolved.lon, lat, lon)
            if distance > radius_m:
                continue
            if item_type == "station":
                counts = {name: props.get(field) for name, field in KIND_FIELDS.items()}
                if kind != "any" and not (counts.get(kind) or 0) > 0:
                    continue
            else:
                vehicle_kind = props.get("form_factor")
                if kind != "any" and vehicle_kind != kind:
                    continue
                counts = None
            current_range = props.get("current_range_meters")
            max_range = props.get("max_range_meters")
            battery_pct = (
                round(current_range / max_range * 100, 1)
                if current_range is not None and max_range
                else None
            )
            is_virtual = item_type == "station" and props.get("is_virtual_station") is True
            items.append(
                compact_dict(
                    {
                        "item_type": item_type,
                        "operator": props.get("feed_id"),
                        "name": props.get("name"),
                        "kind": props.get("form_factor"),
                        "propulsion_type": props.get("propulsion_type"),
                        "available": counts if not is_virtual else None,
                        "virtual_station_inventory": counts if is_virtual else None,
                        "count_semantics": "virtual_station_inventory"
                        if is_virtual
                        else ("physical_station_inventory" if item_type == "station" else None),
                        "current_range_m": current_range,
                        "max_range_m": max_range,
                        "battery_pct": battery_pct,
                        "rental_link": props.get("rental_uris_web"),
                        "lat": lat,
                        "lon": lon,
                        "distance_m": round(distance),
                        **freshness(
                            props.get("last_reported"),
                            outdated=props.get("realtime_data_outdated"),
                        ),
                    }
                )
            )
    items.sort(key=lambda item: item["distance_m"])
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True),
            "radius_m": radius_m,
            "kind": kind,
        },
        count=len(items),
        items=items,
        source=source_info(
            "sharing_stations-and-vehicles", settings.wfs_url, DATASET_LICENSES["wfs"]
        ),
        data_timestamp=latest_datetime([item.get("updated_at") for item in items]),
    ).compact()