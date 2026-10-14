from datetime import date
from typing import Any

from shapely.geometry import Point, box, shape

from ..clients import geocode, static_files
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict, geometry_location
from ..models import BBox, LocationInput, ResultEnvelope, source_info
from .common import latest_datetime, parse_timestamp


def active_in_range(
    properties: dict[str, Any], active_from: date | None, active_to: date | None = None
) -> bool:
    if active_from is None:
        return True
    start = parse_timestamp(properties.get("starttime"))
    end = parse_timestamp(properties.get("endtime"))
    range_end = active_to or active_from
    return (start is None or start.date() <= range_end) and (
        end is None or end.date() >= active_from
    )


async def selected_roadworks(
    area: Any, active_from: date | None, active_to: date | None = None
) -> list[tuple[dict[str, Any], Any]]:
    payload = await static_files.roadworks()
    selected = []
    for feature in payload.get("features", []):
        geometry = shape(feature["geometry"])
        if geometry.intersects(area) and active_in_range(
            feature["properties"], active_from, active_to
        ):
            selected.append((feature, geometry))
    return selected


async def get_roadworks(
    location: LocationInput | dict[str, Any] | None = None,
    bbox: BBox | dict[str, Any] | None = None,
    radius_m: int = 5000,
    active_date: date | None = None,
    active_from: date | None = None,
    active_to: date | None = None,
) -> dict[str, Any]:
    """Find roadworks active on a date or during any day in a date range."""
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
    if active_date is not None and (active_from is not None or active_to is not None):
        raise ValueError("active_date cannot be combined with active_from or active_to")
    effective_from = active_from or active_date or date.today()
    effective_to = active_to or effective_from
    if effective_to < effective_from:
        raise ValueError("active_to must not be before active_from")
    records = await selected_roadworks(area, effective_from, effective_to)
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
            "active_from": effective_from.isoformat(),
            "active_to": effective_to.isoformat(),
        },
        count=len(items),
        items=items,
        source=source_info("roadworks", settings.roadworks_url, DATASET_LICENSES["roadworks"]),
        data_timestamp=latest_datetime([item.get("start") for item in items]),
    ).compact()