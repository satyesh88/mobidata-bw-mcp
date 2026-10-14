import logging
import os
from typing import Any

from shapely.geometry import LineString, shape

from ..models import RoutePoint
from .http import SourceError, http

LOGGER = logging.getLogger(__name__)
OPENROUTESERVICE_URL = (
    "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
)


async def driving_hgv_line(
    route: list[RoutePoint] | list[dict[str, Any]],
) -> LineString | None:
    """Return road-following HGV geometry when an ORS API key is configured."""
    api_key = os.getenv("OPENROUTESERVICE_API_KEY", "").strip()
    if not api_key:
        return None
    points = [
        point if isinstance(point, RoutePoint) else RoutePoint.model_validate(point)
        for point in route
    ]
    try:
        response = await http.request(
            "POST",
            OPENROUTESERVICE_URL,
            headers={"Authorization": api_key},
            json_body={"coordinates": [[point.lon, point.lat] for point in points]},
        )
        payload = response.json()
        geometry = shape(payload["features"][0]["geometry"])
    except (SourceError, ValueError, KeyError, IndexError):
        LOGGER.warning("OpenRouteService routing failed; using straight-line fallback")
        return None
    return geometry if isinstance(geometry, LineString) else None