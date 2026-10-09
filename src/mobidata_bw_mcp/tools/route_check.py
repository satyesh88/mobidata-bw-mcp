from datetime import date
from typing import Any

from shapely.geometry import box

from ..config import DATASET_LICENSES, settings
from ..geo import (
    compact_dict,
    distance_along_route_km,
    route_buffer_m,
    route_line,
    to_local_meters,
)
from ..models import ResultEnvelope, RoutePoint, Vehicle, source_info
from .roadworks import selected_roadworks
from .signs import (
    SIGN_CAVEATS,
    SIGN_MEANINGS,
    TRUCK_CODES,
    normalized_code,
    selected_signs,
    sign_value,
)


async def check_route(
    route: dict[str, Any] | list[RoutePoint],
    buffer_m: int = 30,
    date_value: date | None = None,
    vehicle: Vehicle | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check a caller-supplied route for active roadworks and advisory truck restrictions."""
    line, approximated = route_line(route)
    if buffer_m < 1 or buffer_m > 1000:
        raise ValueError("buffer_m must be between 1 and 1000")
    vehicle_model = Vehicle.model_validate(vehicle) if vehicle else None
    effective_date = date_value or date.today()
    min_lon, min_lat, max_lon, max_lat = line.bounds
    margin = buffer_m / 80_000
    geographic_area = box(
        min_lon - margin, min_lat - margin, max_lon + margin, max_lat + margin
    )
    center = line.centroid
    buffered_route, local_route = route_buffer_m(line, buffer_m)
    roadworks = await selected_roadworks(geographic_area, effective_date)
    signs = await selected_signs(geographic_area, TRUCK_CODES)
    issues = []
    for feature, geometry in roadworks:
        local_geometry = to_local_meters(geometry, center.y, center.x)
        if not local_geometry.intersects(buffered_route):
            continue
        props = feature["properties"]
        issues.append(
            compact_dict(
                {
                    "km_from_start": round(
                        distance_along_route_km(local_route, local_geometry), 2
                    ),
                    "kind": "roadwork",
                    "severity": "high" if props.get("type") == "ROAD_CLOSED" else "warning",
                    "street": props.get("street"),
                    "description": props.get("description") or props.get("subtype"),
                    "start": props.get("starttime"),
                    "end": props.get("endtime"),
                    "source": "MobiData BW roadworks",
                }
            )
        )
    for feature, point in signs:
        local_point = to_local_meters(point, center.y, center.x)
        if not local_point.intersects(buffered_route):
            continue
        raw_code = feature["properties"].get("Verkehrszeichennummer")
        code = normalized_code(raw_code)
        limit_value = sign_value(raw_code)
        exceeded = False
        if vehicle_model and limit_value is not None:
            exceeded = (code == "262" and (vehicle_model.weight_t or 0) > limit_value) or (
                code == "265" and (vehicle_model.height_m or 0) > limit_value
            )
        issues.append(
            compact_dict(
                {
                    "km_from_start": round(
                        distance_along_route_km(local_route, local_point), 2
                    ),
                    "kind": "traffic_sign",
                    "severity": "critical" if exceeded else "warning",
                    "sign_code": code,
                    "description": SIGN_MEANINGS.get(code, raw_code),
                    "limit": limit_value,
                    "vehicle_exceeds_limit": exceeded,
                    "source": "MobiData BW traffic signs",
                }
            )
        )
    issues.sort(key=lambda item: item["km_from_start"])
    roadwork_count = sum(item["kind"] == "roadwork" for item in issues)
    sign_count = len(issues) - roadwork_count
    exceeded_count = sum(bool(item.get("vehicle_exceeds_limit")) for item in issues)
    summary = f"{roadwork_count} roadworks and {sign_count} truck-relevant signs along route"
    if exceeded_count:
        summary += f"; vehicle exceeds {exceeded_count} explicit limits"
    warnings = list(SIGN_CAVEATS)
    if approximated:
        warnings.insert(0, "Straight lines between supplied points approximate the driven route.")
    return ResultEnvelope(
        query={
            "buffer_m": buffer_m,
            "date": effective_date.isoformat(),
            "vehicle": vehicle_model.model_dump(exclude_none=True) if vehicle_model else None,
            "route_length_km": round(local_route.length / 1000, 2),
        },
        count=len(issues),
        items=issues,
        source=source_info(
            "roadworks-and-traffic-signs",
            f"{settings.roadworks_url} + {settings.signs_url}",
            f"{DATASET_LICENSES['roadworks']}; {DATASET_LICENSES['signs']}",
        ),
        warnings=[summary, *warnings],
    ).compact()