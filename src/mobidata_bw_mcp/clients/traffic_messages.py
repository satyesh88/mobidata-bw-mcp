from typing import Any

from cachetools import TTLCache
from defusedxml import ElementTree
from shapely.geometry import LineString, Point

from ..config import settings
from .http import SourceError, http

NS = "{http://datex2.eu/schema/2/2_0}"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

CATEGORIES = {
    "Accident": "accident",
    "AbnormalTraffic": "congestion",
    "MaintenanceWorks": "roadworks",
    "ConstructionWorks": "roadworks",
    "RoadOrCarriagewayOrLaneManagement": "road_management",
    "GeneralNetworkManagement": "road_management",
    "ReroutingManagement": "road_management",
    "VehicleObstruction": "obstruction",
    "GeneralObstruction": "obstruction",
    "InfrastructureDamageObstruction": "obstruction",
    "PublicEvent": "event",
    "Conditions": "conditions",
    "AuthorityOperation": "authority_operation",
}

_cache: TTLCache[str, tuple[str | None, list[dict[str, Any]]]] = TTLCache(
    maxsize=1, ttl=settings.traffic_ttl
)


def _child(element: Any, *names: str) -> Any:
    for name in names:
        if element is None:
            return None
        element = element.find(f"{NS}{name}")
    return element


def _text(element: Any, *names: str) -> str | None:
    node = _child(element, *names)
    return node.text.strip() if node is not None and node.text and node.text.strip() else None


def _point(element: Any) -> tuple[float, float] | None:
    lat, lon = _text(element, "latitude"), _text(element, "longitude")
    return (float(lon), float(lat)) if lat and lon else None


def _comments(record: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    for comment in record.findall(f"{NS}generalPublicComment"):
        kind = _text(comment, "commentType") or "description"
        value = next(
            (
                " ".join(node.text.split())
                for node in comment.iter(f"{NS}value")
                if node.text and node.text.strip()
            ),
            None,
        )
        if value:
            found.setdefault(kind, value)
    return found


def _geometry(record: Any) -> Point | LineString | None:
    group = _child(record, "groupOfLocations")
    if group is None:
        return None
    segment = _child(group, "tpegLinearLocation")
    start = _point(_child(segment, "from", "pointCoordinates"))
    end = _point(_child(segment, "to", "pointCoordinates"))
    if start and end and start != end:
        return LineString([start, end])
    display = _point(_child(group, "locationForDisplay")) or start or end
    return Point(display) if display else None


def _end_time(record: Any) -> str | None:
    explicit = _text(record, "validity", "validityTimeSpecification", "overallEndTime")
    if explicit:
        return explicit
    periods = [
        node.text.strip()
        for node in record.iter(f"{NS}endOfPeriod")
        if node.text and node.text.strip()
    ]
    return max(periods, default=None)  # ISO-8601 UTC strings sort chronologically


def parse(xml_text: str) -> tuple[str | None, list[dict[str, Any]]]:
    root = ElementTree.fromstring(xml_text)
    published = _text(root.find(f".//{NS}payloadPublication"), "publicationTime")
    records = []
    for situation in root.iter(f"{NS}situation"):
        for record in situation.findall(f"{NS}situationRecord"):
            geometry = _geometry(record)
            if geometry is None:
                continue
            kind = record.get(XSI_TYPE) or "Unknown"
            comments = _comments(record)
            records.append(
                {
                    "id": record.get("id"),
                    "type": kind,
                    "category": CATEGORIES.get(kind, "other"),
                    "description": comments.get("description")
                    or next(iter(comments.values()), None),
                    "location_description": comments.get("locationDescriptor"),
                    "start": _text(
                        record, "validity", "validityTimeSpecification", "overallStartTime"
                    ),
                    "end": _end_time(record),
                    "geometry": geometry,
                }
            )
    return published, records


async def messages() -> tuple[str | None, list[dict[str, Any]]]:
    if "data" not in _cache:
        try:
            _cache["data"] = parse(await http.get_text(settings.traffic_messages_url))
        except ElementTree.ParseError as exc:
            raise SourceError("Traffic messages feed returned invalid XML") from exc
    return _cache["data"]
