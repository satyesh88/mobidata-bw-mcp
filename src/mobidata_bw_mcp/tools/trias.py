"""Live stop events and end-to-end public transport journeys from EFA-BW."""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

from ..clients import geocode
from ..clients import trias as api
from ..geo import compact_dict
from ..models import Location, LocationInput, ResultEnvelope, source_info
from ..transit_format import render_departures, render_journeys
from . import transit
from .common import parse_timestamp

BERLIN = ZoneInfo("Europe/Berlin")
CAVEATS = [
    "Live predictions and disruptions are available only when supplied by the operator. "
    "Missing predictions mean scheduled times, not on-time confirmation.",
    "The response timestamp is the source response time, not each observation's update time.",
]


def _text(node: Element | None, path: str) -> str | None:
    if node is None:
        return None
    target = node.find("/".join(f"t:{part}" for part in path.split("/")), api.NS)
    if target is None:
        return None
    text = target.find("t:Text", api.NS)
    return ((text.text if text is not None else target.text) or "").strip() or None


def _find(node: Element, path: str) -> Element | None:
    return node.find("/".join(f"t:{part}" for part in path.split("/")), api.NS)


def _time(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        first = value.replace(tzinfo=BERLIN, fold=0)
        second = value.replace(tzinfo=BERLIN, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("For a daylight-saving clock change, provide an explicit UTC offset.")
        value = first
    return value.astimezone(UTC)


async def _location(value: LocationInput | dict[str, Any]) -> Location | str | api.StopRef:
    if isinstance(value, str) and re.fullmatch(r"de:[\w:_-]+", value):
        return value
    if isinstance(value, str) and re.search(r"\b(?:Hbf|Hauptbahnhof|Bahnhof)\b", value, re.I):
        return await api.resolve_station(value)
    return await geocode.resolve(value)


def _true(node: Element | None, path: str) -> bool:
    return (_text(node, path) or "").lower() in {"true", "1"}


def _now() -> datetime:
    return datetime.now(UTC)


def _call(node: Element | None, arrival: bool = False) -> dict[str, Any]:
    kind = "ServiceArrival" if arrival else "ServiceDeparture"
    planned = _text(node, f"{kind}/TimetabledTime")
    predicted = _text(node, f"{kind}/EstimatedTime")
    planned_dt, predicted_dt = parse_timestamp(planned), parse_timestamp(predicted)
    # TRIAS ServiceTimeGroup defines EstimatedTime as prognosis; no universal live boolean.
    # Future estimates may merely echo the schedule, so only use the near-term horizon.
    live = bool(predicted_dt and planned_dt and planned_dt - _now() <= timedelta(hours=2))
    seconds = (predicted_dt - planned_dt).total_seconds() if live else None
    delay = (int(abs(seconds) / 60 + 0.5) * (1 if seconds >= 0 else -1)) if live else None
    return compact_dict(
        {
            "stop_id": _text(node, "StopPointRef"),
            "stop_name": _text(node, "StopPointName"),
            "scheduled_time": planned,
            "estimated_time": predicted,
            "time": predicted if live else planned,
            "delay_minutes": 0 if live and abs(seconds) < 60 else delay,
            "platform": _text(node, "EstimatedBay") or _text(node, "PlannedBay"),
            "scheduled_platform": _text(node, "PlannedBay"),
            "platform_changed": bool(
                _text(node, "EstimatedBay")
                and _text(node, "PlannedBay")
                and _text(node, "EstimatedBay") != _text(node, "PlannedBay")
            ),
            "is_live": live,
            "cancelled": _true(node, "NotServicedStop"),
        }
    )


def _service(node: Element | None) -> dict[str, Any]:
    sections = node.findall("t:ServiceSection", api.NS) if node is not None else []
    primary = sections[0] if sections else node
    notes = []
    if node is not None:
        for attribute in node.findall("t:Attribute", api.NS):
            text = _text(attribute, "Text")
            if text:
                notes.append(text)
    return compact_dict(
        {
            "route": _text(primary, "PublishedLineName"),
            "headsign": _text(node, "DestinationText"),
            "mode": _text(primary, "Mode/PtMode"),
            "journey_id": _text(node, "JourneyRef"),
            "operator": _text(primary, "OperatorRef"),
            "cancelled": _true(node, "Cancelled"),
            "wheelchair_accessible": "unknown",
            "service_notes": notes or None,
            "service_sections": [
                compact_dict(
                    {
                        "route": _text(section, "PublishedLineName"),
                        "mode": _text(section, "Mode/PtMode"),
                    }
                )
                for section in sections
            ]
            if len(sections) > 1
            else None,
        }
    )


def _warnings(document: Element) -> list[str]:
    warnings = list(CAVEATS)
    for node in document.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"Situation", "PtSituationElement"}:
            continue
        for child in node:
            if child.tag.rsplit("}", 1)[-1] in {"Summary", "Description"}:
                text = (child.text or "").strip() or " ".join(
                    (part.text or "").strip()
                    for part in child.iter()
                    if part.tag.rsplit("}", 1)[-1] == "Text"
                )
                if text and text not in warnings:
                    warnings.append(text[:600])
    if document.findall(".//t:ErrorMessage", api.NS):
        warnings.append("Some TRIAS results contain source warnings; details may be incomplete.")
    return warnings


def _envelope(
    document: Element, query: dict, items: list[dict], limit: int, warnings: list[str]
) -> dict:
    stamp = document.find(".//s:ResponseTimestamp", api.NS)
    result = ResultEnvelope(
        query=query,
        count=len(items),
        items=items,
        truncated=len(items) >= limit,
        source=source_info(
            "EFA-BW TRIAS",
            "https://mobidata-bw.de/dataset/trias",
            "Datenlizenz Deutschland - Namensnennung 2.0",
        ),
        data_timestamp=parse_timestamp(stamp.text if stamp is not None else None),
        warnings=warnings,
    ).compact()
    result["compact_list"] = (
        render_journeys(result) if items and "legs" in items[0] else render_departures(result)[0]
    )
    return result


def _departure_request(
    value: Location | str | api.StopRef, start: datetime, end: datetime, limit: int
) -> Element:
    request = Element("StopEventRequest")
    api.location(request, "Location", value, start)
    params = api.add(request, "Params")
    api.add(params, "NumberOfResults", limit)
    api.add(params, "TimeWindow", f"PT{int((end - start).total_seconds())}S")
    api.add(params, "StopEventType", "departure")
    api.add(params, "IncludeRealtimeData", "true")
    return request


async def _departure_pages(
    target: Location | str | api.StopRef, start: datetime, end: datetime, limit: int
) -> tuple[list[Element], bool]:
    """Cover the window using overlapping scheduled-time pages, including tied times."""
    documents = []
    cursor = start
    requested = max(30, limit)
    try:
        async with asyncio.timeout(10):
            for _ in range(8):
                document = await api.request(_departure_request(target, cursor, end, requested))
                documents.append(document)
                events = document.findall(".//t:StopEvent", api.NS)
                times = [
                    parse_timestamp(
                        _text(
                            _find(event, "ThisCall/CallAtStop"), "ServiceDeparture/TimetabledTime"
                        )
                    )
                    for event in events
                ]
                times = [time for time in times if time is not None]
                if len(events) < requested or times and max(times) > end:
                    return documents, True
                if not times:
                    return documents, False
                latest = max(times)
                if latest <= cursor:
                    if requested >= 240:
                        return documents, False
                    requested *= 2  # retrieve all departures tied at this timestamp
                else:
                    cursor = latest  # overlap the boundary; merged identities remove duplicates
            return documents, False
    except TimeoutError:
        if not documents:
            raise api.TriasError("source_timeout") from None
        return documents, False
    except api.TriasError:
        if not documents:
            raise
        return documents, False


async def get_live_departures(
    stop_or_location: LocationInput | dict[str, Any],
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    limit: int = 10,
    fallback_to_schedule: bool = True,
    cursor: int = 0,
) -> dict[str, Any]:
    """Get TRIAS departures with scheduled/predicted times, delays and cancellations.

    Supply a station/place or coordinates once; do not loop over platform IDs.
    Coordinates query up to three stop groups within 500 m. GTFS fallback is labelled scheduled.
    Naive times mean Europe/Berlin. Missing predictions never confirm on-time running.
    Source requests page through the window. Pass next_cursor back as cursor for more results.
    """
    if not 1 <= limit <= 30 or cursor < 0:
        raise ValueError("limit must be between 1 and 30 and cursor must not be negative")
    start = _time(time_from)
    end = _time(time_to) if time_to else start + timedelta(minutes=90)
    if end <= start or end - start > timedelta(hours=6):
        raise ValueError("The departure window must be positive and at most six hours.")
    try:
        api.configuration()
        resolved = await _location(stop_or_location)
        targets = await api.nearby_stops(resolved) if isinstance(resolved, Location) else [resolved]
        responses = await asyncio.gather(
            *(_departure_pages(target, start, end, limit) for target in targets),
            return_exceptions=True,
        )
        documents = [
            document
            for response in responses
            if isinstance(response, tuple)
            for document in response[0]
        ]
        complete = all(isinstance(response, tuple) and response[1] for response in responses)
        failures = [response for response in responses if isinstance(response, BaseException)]
        if not documents:
            failure = failures[0]
            if isinstance(failure, api.TriasError):
                raise failure
            if isinstance(failure, asyncio.CancelledError):
                raise failure
            raise api.TriasError("source_unavailable")
        document = documents[0]
    except api.TriasError as error:
        if not fallback_to_schedule:
            return _error(error)
        location = (
            stop_or_location
            if isinstance(stop_or_location, str)
            else Location.model_validate(stop_or_location)
        )
        stop = location if isinstance(location, str) else f"{location.lat},{location.lon}"
        result = await transit.get_departures(stop, time_from=start, time_to=end, limit=limit)
        result["window_complete"] = not result.get("truncated", False)
        result.setdefault("warnings", []).insert(
            0, f"TRIAS {error.code}; GTFS fallback is scheduled only. No live status is available."
        )
        result.setdefault("query", {})["realtime_status"] = error.code
        for item in result.get("items", []):
            item["is_live"] = False
        return result
    items = []
    seen = set()
    for source_document in documents:
        for event in source_document.findall(".//t:StopEvent", api.NS):
            call = _call(_find(event, "ThisCall/CallAtStop"))
            service = _service(_find(event, "Service"))
            stamp = parse_timestamp(call.get("time"))
            identity = (
                service.get("journey_id"),
                call.get("stop_id"),
                call.get("scheduled_time"),
                service.get("route"),
            )
            if stamp is None or not start <= stamp <= end or identity in seen:
                continue
            seen.add(identity)
            items.append(
                {**service, **call, "cancelled": service["cancelled"] or call["cancelled"]}
            )
    items.sort(key=lambda item: parse_timestamp(item["scheduled_time"]))
    warnings = list(
        dict.fromkeys(
            warning for source_document in documents for warning in _warnings(source_document)
        )
    )
    if failures or not complete:
        warnings.append(
            "Some departures could not be verified; these results are partial. Please try again."
        )
    if isinstance(resolved, api.StopRef):
        warnings.append(
            "Station names use TRIAS's primary matching stop; "
            "adjacent station groups may need a more specific stop name."
        )
    if not items:
        warnings.append(
            "TRIAS returned no departures in this window; this is not a source timeout."
        )
    if isinstance(resolved, Location):
        warnings.append(
            "Coordinate searches query up to three nearby stop groups within 500 m; "
            "check each stop name. The nearby-stop list may be incomplete."
        )
    page = items[cursor : cursor + limit]
    result = _envelope(
        document,
        {
            "stop_or_location": stop_or_location,
            "location": resolved.model_dump() if isinstance(resolved, Location) else None,
            "resolved_stop": {"id": resolved.ref, "name": resolved.name}
            if isinstance(resolved, api.StopRef)
            else None,
            "time_from": start.isoformat(),
            "time_to": end.isoformat(),
            "limit": limit,
            "cursor": cursor,
        },
        page,
        limit,
        warnings,
    )
    more = cursor + len(page) < len(items)
    result["truncated"] = more or not complete
    result["window_complete"] = complete and not more
    if more:
        result["next_cursor"] = cursor + len(page)
    result["available_count"] = len(items)
    result["compact_list"] = render_departures(result)[0]
    return result


def _error(error: api.TriasError) -> dict:
    return {
        "error": error.code,
        "partial": True,
        "message": "The TRIAS source didn’t respond with usable data. "
        "Please try again; no journey or live-status claim can be made.",
    }


async def plan_transit_journey(
    origin: LocationInput | dict[str, Any],
    destination: LocationInput | dict[str, Any],
    departure_time: datetime | None = None,
    arrival_time: datetime | None = None,
    wheelchair: bool = False,
    max_transfers: int | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Plan A-to-B public transport journeys through EFA-BW TRIAS, including arrive-by searches.

    Provide either departure_time or arrival_time. Naive times mean Europe/Berlin.
    wheelchair requests no steps/stairs/escalators and level boarding; it is not a guarantee
    of accessibility or working lifts. Predictions and disruptions depend on source coverage.
    """
    if departure_time is not None and arrival_time is not None:
        raise ValueError("Supply departure_time or arrival_time, not both")
    if not 1 <= limit <= 5 or max_transfers is not None and not 0 <= max_transfers <= 5:
        raise ValueError("limit must be 1–5 and max_transfers 0–5")
    when = _time(arrival_time if arrival_time is not None else departure_time)
    try:
        api.configuration()
        # Resolve sequentially to respect Nominatim's own rate limiter.
        start, end = await _location(origin), await _location(destination)
        request = Element("TripRequest")
        api.location(request, "Origin", start, when if arrival_time is None else None)
        api.location(request, "Destination", end, when if arrival_time is not None else None)
        params = api.add(request, "Params")
        if wheelchair:
            for name in ["NoSingleStep", "NoStairs", "NoEscalator", "LevelEntrance"]:
                api.add(params, name, "true")
        api.add(params, "NumberOfResults", limit)
        if max_transfers:
            api.add(params, "InterchangeLimit", max_transfers)
        api.add(params, "IncludeAccessibility", "true")
        api.add(params, "IncludeEstimatedTimes", "true")
        api.add(params, "IncludeSituationInfo", "true")
        document = await api.request(request)
    except api.TriasError as error:
        return _error(error)
    items = []
    for trip in document.findall(".//t:TripResult/t:Trip", api.NS):
        legs = []
        for leg in trip.findall("t:TripLeg", api.NS):
            timed = _find(leg, "TimedLeg")
            if timed is not None:
                service = _service(_find(timed, "Service"))
                board, alight = (
                    _call(_find(timed, "LegBoard")),
                    _call(_find(timed, "LegAlight"), arrival=True),
                )
                legs.append(
                    {
                        "kind": "public_transport",
                        **service,
                        "board": board,
                        "alight": alight,
                        "cancelled": service["cancelled"]
                        or board["cancelled"]
                        or alight["cancelled"],
                    }
                )
            else:
                node = _find(leg, "InterchangeLeg")
                kind = "transfer"
                if node is None:
                    node = _find(leg, "ContinuousLeg")
                    kind = "access_or_egress"
                legs.append(
                    compact_dict(
                        {
                            "kind": kind,
                            "duration": _text(node, "Duration"),
                            "start_time": _text(node, "TimeWindowStart"),
                            "end_time": _text(node, "TimeWindowEnd"),
                            "from": _text(node, "LegStart/LocationName"),
                            "to": _text(node, "LegEnd/LocationName"),
                            "mode": _text(node, "InterchangeMode")
                            or _text(node, "Service/ContinuousMode"),
                            "description": _text(node, "LegDescription"),
                        }
                    )
                )
        transfers = int(_text(trip, "Interchanges") or 0)
        if max_transfers is not None and transfers > max_transfers:
            continue
        departure = parse_timestamp(_text(trip, "StartTime"))
        arrival = parse_timestamp(_text(trip, "EndTime"))
        if (
            departure is None
            or arrival is None
            or (arrival_time is not None and arrival > when)
            or (arrival_time is None and departure < when)
        ):
            continue
        items.append(
            compact_dict(
                {
                    "trip_id": _text(trip, "TripId"),
                    "departure": _text(trip, "StartTime"),
                    "arrival": _text(trip, "EndTime"),
                    "duration": _text(trip, "Duration"),
                    "transfers": transfers,
                    "legs": legs,
                    "cancelled": any(leg.get("cancelled", False) for leg in legs),
                    "is_live": any(
                        leg.get("board", {}).get("is_live", False)
                        or leg.get("alight", {}).get("is_live", False)
                        for leg in legs
                    ),
                    "wheelchair_accessible": "unknown",
                    "accessibility_preferences_requested": wheelchair,
                }
            )
        )
    items.sort(key=lambda item: item.get("arrival" if arrival_time else "departure", ""))
    warnings = _warnings(document)
    if wheelchair:
        warnings.append(
            "Wheelchair preferences were requested, not independently verified. "
            "Lift operation and end-to-end accessibility are not guaranteed."
        )
    if not items:
        warnings.append("No matching journey was returned; this does not prove none exists.")
    if max_transfers == 0:
        warnings.append("Direct journeys are filtered locally; other direct options may exist.")
    return _envelope(
        document,
        {
            "origin": origin,
            "destination": destination,
            "requested_time": when.isoformat(),
            "arrive_by": arrival_time is not None,
            "wheelchair": wheelchair,
            "max_transfers": max_transfers,
            "limit": limit,
            "coordinate_access_limit_minutes": 15
            if isinstance(start, Location) or isinstance(end, Location)
            else None,
        },
        items[:limit],
        limit,
        warnings,
    )
