from typing import Any

from ..clients import geocode, wfs
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, geometry_location, haversine_m
from ..models import BBox, LocationInput, ResultEnvelope, source_info
from .common import limit_value


async def query_layer(
    layer: str,
    location: LocationInput | dict[str, Any] | None = None,
    bbox: BBox | dict[str, Any] | None = None,
    radius_m: int = 1000,
    filter: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Query any current WFS layer by location or bbox. CQL supports simple comparisons only."""
    if location is None and bbox is None:
        raise ValueError("location or bbox is required")
    resolved = await geocode.resolve(location) if location is not None else None
    resolved_bbox = (
        BBox.model_validate(bbox) if bbox is not None else bbox_around(resolved, radius_m)
    )
    bounded = limit_value(limit)
    payload = await wfs.features(
        layer, bbox=resolved_bbox, cql_filter=filter, limit=bounded + 1
    )
    items = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry")
        item: dict[str, Any] = {"properties": feature.get("properties", {})}
        if geometry:
            lat, lon = geometry_location(geometry)
            item.update({"lat": lat, "lon": lon, "geometry": geometry})
            if resolved:
                item["distance_m"] = round(haversine_m(resolved.lat, resolved.lon, lat, lon))
        items.append(item)
    if resolved:
        items.sort(key=lambda item: item.get("distance_m", float("inf")))
        items = [item for item in items if item.get("distance_m", radius_m + 1) <= radius_m]
    truncated = len(items) > bounded
    items = items[:bounded]
    return ResultEnvelope(
        query={
            "layer": layer,
            "location": resolved.model_dump(exclude_none=True) if resolved else None,
            "bbox": resolved_bbox.model_dump(),
            "radius_m": radius_m if resolved else None,
            "filter": filter,
            "limit": bounded,
        },
        count=len(items),
        truncated=truncated,
        items=items,
        source=source_info(layer, settings.wfs_url, DATASET_LICENSES["wfs"]),
    ).compact()