import math
from collections.abc import Iterable
from typing import Any

from shapely import transform
from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry

from .models import BBox, Location, RoutePoint

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def bbox_around(location: Location, radius_m: float) -> BBox:
    lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
    lon_delta = lat_delta / max(math.cos(math.radians(location.lat)), 0.01)
    return BBox(
        min_lat=location.lat - lat_delta,
        min_lon=location.lon - lon_delta,
        max_lat=location.lat + lat_delta,
        max_lon=location.lon + lon_delta,
    )


def geometry_location(geometry: dict[str, Any]) -> tuple[float, float]:
    point = shape(geometry).representative_point()
    return point.y, point.x


def route_line(route: dict[str, Any] | list[RoutePoint]) -> tuple[LineString, bool]:
    if isinstance(route, dict):
        geometry = shape(route)
        if not isinstance(geometry, LineString):
            raise ValueError("route GeoJSON must be a LineString")
        return geometry, False
    if len(route) < 2:
        raise ValueError("route requires at least two points")
    points = [
        point if isinstance(point, RoutePoint) else RoutePoint.model_validate(point)
        for point in route
    ]
    return LineString([(point.lon, point.lat) for point in points]), True


def to_local_meters(geometry: BaseGeometry, origin_lat: float, origin_lon: float) -> BaseGeometry:
    cos_lat = math.cos(math.radians(origin_lat))

    def project(coordinates: Any) -> Any:
        result = coordinates.copy()
        result[:, 0] = (
            (coordinates[:, 0] - origin_lon) * math.pi / 180 * EARTH_RADIUS_M * cos_lat
        )
        result[:, 1] = (coordinates[:, 1] - origin_lat) * math.pi / 180 * EARTH_RADIUS_M
        return result

    return transform(geometry, project)


def route_buffer_m(route: LineString, distance_m: float) -> tuple[BaseGeometry, LineString]:
    center = route.centroid
    local_route = to_local_meters(route, center.y, center.x)
    return local_route.buffer(distance_m), local_route


def distance_along_route_km(local_route: LineString, geometry: BaseGeometry) -> float:
    nearest = local_route.interpolate(local_route.project(geometry.centroid))
    return local_route.project(nearest) / 1000


def compact_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def newest_timestamp(values: Iterable[str | None]) -> str | None:
    available = [value for value in values if value]
    return max(available) if available else None