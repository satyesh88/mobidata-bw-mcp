from datetime import date
from typing import Any

from shapely.geometry import Point, box, shape

from ..clients import geocode, static_files
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict, geometry_location
from ..models import BBox, LocationInput, ResultEnvelope, source_info
from .common import latest_datetime, parse_timestamp


def active_on(properties: dict[str, Any], active_date: date | None) -> bool:
    if active_date is None:
        return True
    start = parse_timestamp(properties.get("starttime"))
    end = parse_timestamp(properties.get("endtime"))
    return (start is None or start.date() <= active_date) and (
        end is None or end.date() >= active_date
    )


async def selected_roadworks(
    area: Any, active_date: date | None
) -> list[tuple[dict[str, Any], Any]]:
    payload = await static_files.roadworks()
    selected = []
    for feature in payload.get("features", []):
        geometry = shape(feature["geometry"])
        if geometry.intersects(area) and active_on(feature["properties"], active_date):
            selected.append((feature, geometry))
    return selected


async def get_roadworks(
    location: LocationInput | dict[str, Any] | None = None,
    bbox: BBox | dict[str, Any] | None = None,
    radius_m: int = 5000,
    active_date: date | None = None,
) -> dict[str, Any]:
    """Find planned or current roadworks by radius or bbox, optionally active on a date."""
    if location is None and bbox is None:
        raise ValueError("location or bbox is required")
    resolved = await geocode.resolve(location) if location is not None else None
    parsed_bbox = BBox.model_validate(bbox) if bbox is not None else None
    if resolved:
        radius_bbox = bbox_around(resolved, radius_m)
        area = box(
            radius_bbox.min_lon,
            radius_bbox.min_lat,
            radius_bbox.max_lon,
            radius_bbox.max_lat,
        )
    else:
        area = box(
            parsed_bbox.min_lon,
            parsed_bbox.min_lat,
            parsed_bbox.max_lon,
            parsed_bbox.max_lat,
        )
    effective_date = active_date or date.today()
    records = await selected_roadworks(area, effective_date)
    items = []
    for feature, geometry in records:
        props = feature["properties"]
        lat, lon = geometry_location(feature["geometry"])
        if resolved:
            distance = geometry.distance(Point(resolved.lon, resolved.lat)) * 111_320
            if distance > radius_m:
                continue
        else:
            distance = None
        items.append(
            compact_dict(
                {
                    "id": props.get("id"),
                    "street": props.get("street"),
                    "type": props.get("type"),
                    "subtype": props.get("subtype"),
                    "description": props.get("description"),
                    "direction": props.get("direction"),
                    "start": props.get("starttime"),
                    "end": props.get("endtime"),
                    "lat": lat,
                    "lon": lon,
                    "distance_m": round(distance) if distance is not None else None,
                    "geometry_type": geometry.geom_type,
                }
            )
        )
    if resolved:
        items.sort(key=lambda item: item["distance_m"])
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True) if resolved else None,
            "bbox": parsed_bbox.model_dump() if parsed_bbox else None,
            "radius_m": radius_m if resolved else None,
            "active_on": effective_date.isoformat(),
        },
        count=len(items),
        items=items,
        source=source_info("roadworks", settings.roadworks_url, DATASET_LICENSES["roadworks"]),
        data_timestamp=latest_datetime([item.get("start") for item in items]),
    ).compact()