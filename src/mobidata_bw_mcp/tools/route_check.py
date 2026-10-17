from datetime import date
from typing import Any

from shapely.geometry import box

from ..clients import routing
from ..clients.http import SourceError
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
    sign_unit,
    sign_value,
)
from .traffic_messages import TRAFFIC_CAVEATS, selected_traffic_messages, severity


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
    route_source = "provided_geometry"
    if approximated:
        routed_line = await routing.driving_hgv_line(route)
        if routed_line is not None:
            line = routed_line
            approximated = False
            route_source = "openrouteservice_driving_hgv"
        else:
            route_source = "straight_line_waypoints"
    effective_buffer_m = max(buffer_m, 500) if approximated else buffer_m
    min_lon, min_lat, max_lon, max_lat = line.bounds
    margin = effective_buffer_m / 80_000
    geographic_area = box(
        min_lon - margin, min_lat - margin, max_lon + margin, max_lat + margin
    )
    center = line.centroid
    buffered_route, local_route = route_buffer_m(line, effective_buffer_m)
    roadworks = await selected_roadworks(geographic_area, effective_date)
    signs = await selected_signs(geographic_area, TRUCK_CODES)
    traffic_warning = None
    try:
        _published, traffic = await selected_traffic_messages(geographic_area, effective_date)
    except SourceError:
        traffic = []
        traffic_warning = "Traffic messages were unavailable; incidents are not included."
    issues = []
    for feature, geometry in roadworks:
        local_geometry = to_local_meters(geometry, center.y, center.x)
        if not local_geometry.intersects(buffered_route):
            continue
        distance_to_route_m = local_geometry.distance(local_route)
        props = feature["properties"]
        issues.append(
            compact_dict(
                {
                    "km_from_start": round(
                        distance_along_route_km(local_route, local_geometry), 2
                    ),
                    "kind": "roadwork",
                    "route_relation": (
                        "on_route" if distance_to_route_m <= buffer_m else "near_route"
                    ),
                    "distance_to_route_m": round(distance_to_route_m),
                    "severity": "high" if props.get("type") == "ROAD_CLOSED" else "warning",
                    "type": props.get("type"),
                    "subtype": props.get("subtype"),
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
        distance_to_route_m = local_point.distance(local_route)
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
                    "route_relation": (
                        "on_route" if distance_to_route_m <= buffer_m else "near_route"
                    ),
                    "distance_to_route_m": round(distance_to_route_m),
                    "severity": "critical" if exceeded else "warning",
                    "sign_code": code,
                    "description": SIGN_MEANINGS.get(code, raw_code),
                    "limit": limit_value,
                    "limit_unit": sign_unit(raw_code),
                    "vehicle_exceeds_limit": exceeded,
                    "source": "MobiData BW traffic signs",
                }
            )
        )
    for message in traffic:
        local_geometry = to_local_meters(message["geometry"], center.y, center.x)
        if not local_geometry.intersects(buffered_route):
            continue
        distance_to_route_m = local_geometry.distance(local_route)
        issues.append(
            compact_dict(
                {
                    "km_from_start": round(
                        distance_along_route_km(local_route, local_geometry), 2
                    ),
                    "kind": "traffic_message",
                    "route_relation": (
                        "on_route" if distance_to_route_m <= buffer_m else "near_route"
                    ),
                    "distance_to_route_m": round(distance_to_route_m),
                    "severity": severity(message),
                    "category": message["category"],
                    "description": message["description"],
                    "location_description": message["location_description"],
                    "start": message["start"],
                    "end": message["end"],
                    "source": "MobiData BW traffic messages",
                }
            )
        )
    issues.sort(key=lambda item: item["km_from_start"])
    roadwork_count = sum(item["kind"] == "roadwork" for item in issues)
    message_count = sum(item["kind"] == "traffic_message" for item in issues)
    sign_count = len(issues) - roadwork_count - message_count
    exceeded_count = sum(bool(item.get("vehicle_exceeds_limit")) for item in issues)
    on_route_count = sum(item["route_relation"] == "on_route" for item in issues)
    near_route_count = len(issues) - on_route_count
    summary = (
        f"{on_route_count} findings on the route and {near_route_count} near the route "
        f"({roadwork_count} roadworks, {message_count} traffic messages, "
        f"{sign_count} truck-relevant signs)"
    )
    if exceeded_count:
        summary += f"; vehicle exceeds {exceeded_count} explicit limits"
    warnings = list(SIGN_CAVEATS)
    if traffic:
        warnings.extend(TRAFFIC_CAVEATS)
    if traffic_warning:
        warnings.append(traffic_warning)
    if approximated:
        warnings.insert(0, "Straight lines between supplied points approximate the driven route.")
    return ResultEnvelope(
        query={
            "buffer_m": buffer_m,
            "effective_buffer_m": effective_buffer_m,
            "route_source": route_source,
            "date": effective_date.isoformat(),
            "vehicle": vehicle_model.model_dump(exclude_none=True) if vehicle_model else None,
            "route_length_km": round(local_route.length / 1000, 2),
        },
        count=len(issues),
        items=issues,
        source=source_info(
            "roadworks-traffic-messages-and-traffic-signs",
            f"{settings.roadworks_url} + {settings.traffic_messages_url} + {settings.signs_url}",
            "; ".join(
                DATASET_LICENSES[key] for key in ("roadworks", "traffic_messages", "signs")
            ),
        ),
        warnings=[summary, *warnings],
    ).compact()