from datetime import date
from typing import Any

from shapely.geometry import Point, box

from ..clients import geocode, traffic_messages
from ..config import DATASET_LICENSES, settings
from ..geo import bbox_around, compact_dict, to_local_meters
from ..models import LocationInput, ResultEnvelope, source_info
from .common import freshness, limit_value, parse_timestamp
from .roadworks import active_in_range

TRAFFIC_CAVEATS = [
    "Traffic messages are a state-wide situation snapshot (DATEX II) and may lag real conditions.",
    "Message texts are German and published by the traffic management centre.",
]


def feed_warnings(published: str | None) -> list[str]:
    warnings = list(TRAFFIC_CAVEATS)
    status = freshness(published)
    if not status["is_live"]:
        warnings.append(f"Traffic message feed was published {status['age_minutes']} min ago")
    return warnings


def severity(message: dict[str, Any]) -> str:
    text = (message.get("description") or "").casefold()
    if message["category"] == "accident" or "gesperrt" in text or "sperrung" in text:
        return "high"
    return "warning"


async def selected_traffic_messages(
    area: Any, active_from: date | None, active_to: date | None = None
) -> tuple[str | None, list[dict[str, Any]]]:
    published, records = await traffic_messages.messages()
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        if not record["geometry"].intersects(area) or not active_in_range(
            {"starttime": record["start"], "endtime": record["end"]}, active_from, active_to
        ):
            continue
        # One situation often has several records (works, lane management) with one text.
        key = (record["description"], record["geometry"].wkt)
        unique.setdefault(key, record)
    return published, list(unique.values())


async def find_traffic_messages(
    location: LocationInput | dict[str, Any],
    radius_m: int = 5000,
    limit: int = 20,
) -> dict[str, Any]:
    """Find current traffic messages (accidents, congestion, closures, obstructions, works)."""
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    bounded_limit = limit_value(limit)
    resolved = await geocode.resolve(location)
    radius_bbox = bbox_around(resolved, radius_m)
    area = box(
        radius_bbox.min_lon, radius_bbox.min_lat, radius_bbox.max_lon, radius_bbox.max_lat
    )
    published, records = await selected_traffic_messages(area, date.today())
    origin = Point(0, 0)
    items = []
    for record in records:
        local = to_local_meters(record["geometry"], resolved.lat, resolved.lon)
        distance = local.distance(origin)
        if distance > radius_m:
            continue
        point = record["geometry"].representative_point()
        items.append(
            compact_dict(
                {
                    "id": record["id"],
                    "category": record["category"],
                    "type": record["type"],
                    "severity": severity(record),
                    "description": record["description"],
                    "location_description": record["location_description"],
                    "start": record["start"],
                    "end": record["end"],
                    "lat": point.y,
                    "lon": point.x,
                    "distance_m": round(distance),
                }
            )
        )
    items.sort(key=lambda item: item["distance_m"])
    shown = items[:bounded_limit]
    return ResultEnvelope(
        query={
            "location": resolved.model_dump(exclude_none=True),
            "radius_m": radius_m,
            "limit": bounded_limit,
        },
        count=len(shown),
        truncated=len(items) > bounded_limit,
        items=shown,
        source=source_info(
            "meldung", settings.traffic_messages_url, DATASET_LICENSES["traffic_messages"]
        ),
        data_timestamp=parse_timestamp(published),
        warnings=feed_warnings(published),
    ).compact()
