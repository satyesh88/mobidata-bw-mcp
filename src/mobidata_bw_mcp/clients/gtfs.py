import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

from cachetools import TTLCache

from ..config import settings
from ..geo import bbox_around
from . import geocode, wfs
from .http import http

_stop_cache: TTLCache[str, list[str]] = TTLCache(maxsize=512, ttl=86400)
_departure_cache: TTLCache[tuple, dict] = TTLCache(maxsize=512, ttl=600)
COLUMNS = (
    "route_short_name,trip_headsign,t_departure,departure_time,"
    "stop_id,stop_name,station_name,wheelchair_accessible"
)


def wheelchair_status(value: Any) -> str:
    """GTFS 0 is unspecified, never evidence of inaccessibility."""
    normalized = str(value).strip().casefold() if value is not None else ""
    return {
        "0": "unknown", "1": "accessible", "2": "not_accessible",
        "unknown": "unknown", "no_info_or_inherit": "unknown",
        "accessible": "accessible", "not_accessible": "not_accessible",
    }.get(normalized, "unknown")


# The mainline station and its named forecourt Stadtbahn stops have separate GTFS
# parents. Merge only these explicitly verified station-complex names, not a city search.
_HEILBRONN_COMPLEX = {
    "heilbronn hbf", "heilbronn hauptbahnhof", "de:08121:26", "de:08121:26_parent",
    "heilbronn hbf/willy-brandt-platz", "heilbronn hbf/willy-brandt-pl.",
}


async def _query(url: str, params: dict[str, Any], *, timeout: float = 4) -> Any:
    started = time.perf_counter()
    outcome = "ok"
    try:
        return await http.get_json(url, params, timeout=timeout, attempts=1)
    except BaseException as exc:
        outcome = type(exc).__name__
        raise
    finally:
        logging.getLogger(__name__).info(
            "departures_query resource=%s duration_ms=%.1f outcome=%s",
            url.rsplit("/", 1)[-1],
            (time.perf_counter() - started) * 1000,
            outcome,
        )


async def resolve_stop_ids(value: str) -> list[str]:
    key = value.strip().casefold()
    if key in _stop_cache:
        return _stop_cache[key]
    if (value.startswith("de:") or value.isdigit()) and key not in _HEILBRONN_COMPLEX:
        ids = [value]
        if value.endswith("_Parent"):
            children = await _query(
                f"{settings.gtfs_url}stops",
                {
                    "parent_station": f"eq.{value}",
                    "select": "stop_id",
                    "limit": 1000,
                },
            )
            ids.extend(row["stop_id"] for row in children)
    else:
        name = re.sub(r"\bHbf\b", "Hauptbahnhof", value.strip(), flags=re.I)
        params = {
            "stop_name": f"ilike.{name}",
            "select": "stop_id,parent_station",
            "limit": 100,
        }
        if key in _HEILBRONN_COMPLEX:
            params.pop("stop_name")
            params["or"] = (
                "(stop_name.eq.Heilbronn Hauptbahnhof,"
                "stop_name.ilike.Heilbronn Hbf/Willy-Brandt-Pl.*)"
            )
        # Also accept coordinate strings without changing the public tool schema.
        coordinates = re.fullmatch(r"\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*", value)
        if coordinates:
            lat, lon = map(float, coordinates.groups())
            location = await geocode.resolve({"lat": lat, "lon": lon})
            nearby = await wfs.features(
                "MobiData-BW:transit_stops", bbox=bbox_around(location, 300), limit=100
            )
            ids = [row["properties"]["stop_id"] for row in nearby.get("features", [])]
            if ids:
                _stop_cache[key] = ids
            return ids
        rows = await _query(f"{settings.gtfs_url}stops", params)
        ids = [row["stop_id"] for row in rows]
        parents = list(
            dict.fromkeys(row["parent_station"] for row in rows if row.get("parent_station"))
        )
        # Expand parent stations once so departures need only the indexed stop_id filter.
        if parents:
            quoted = ",".join('"' + item.replace('"', "") + '"' for item in parents)
            children = await _query(
                f"{settings.gtfs_url}stops",
                {
                    "parent_station": f"in.({quoted})",
                    "select": "stop_id",
                    "limit": 1000,
                },
            )
            ids.extend(row["stop_id"] for row in children)
        ids = list(dict.fromkeys(ids))
    if ids:
        _stop_cache[key] = ids
    return ids


async def departures(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Narrow the expensive calendar-expanding view by indexed candidate trip IDs."""
    async with asyncio.timeout(4.5):
        return await _bounded_departures(params)


async def _bounded_departures(params: dict[str, Any]) -> list[dict[str, Any]]:
    start = datetime.fromisoformat(params["_start"])
    end = start + timedelta(minutes=90)
    stop_filter = params["stop_id"]
    candidates: list[str] = []
    # GTFS service-day intervals may exceed 24:00. Include the previous service day
    # and the next day for windows crossing midnight; the final timestamp filter
    # below decides which dated departures actually belong to the requested window.
    windows = []
    for day_offset in (-1, 0, 1):
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=day_offset
        )
        lower = (start.replace(tzinfo=None) - midnight.replace(tzinfo=None)).total_seconds()
        upper = (end.replace(tzinfo=None) - midnight.replace(tzinfo=None)).total_seconds()
        if upper <= 0:
            continue

        def interval(seconds: float) -> str:
            hours, remainder = divmod(int(max(0, seconds)), 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02}:{minutes:02}:{seconds:02}"

        windows.append(
            f"and(departure_time.gte.{interval(lower)},departure_time.lt.{interval(upper)})"
        )

    offset = 0
    while True:
        rows = await _query(
            f"{settings.gtfs_url}stop_times",
            {
                "stop_id": stop_filter,
                "select": "trip_id",
                "or": "(" + ",".join(windows) + ")",
                "order": "departure_time,trip_id,stop_sequence",
                "limit": 20,
                "offset": offset,
            },
        )
        candidates.extend(row["trip_id"] for row in rows)
        if len(rows) < 20:
            break
        offset += 20

    trips = list(dict.fromkeys(candidates))
    if not trips:
        return []
    quoted = ",".join('"' + value.replace('"', "") + '"' for value in trips)
    query = {key: value for key, value in params.items() if not key.startswith("_")}
    query["trip_id"] = f"in.({quoted})"
    query["date"] = f"gte.{(start.date() - timedelta(days=1)).isoformat()}"
    query["and"] = query["and"][:-1] + f",date.lte.{end.date().isoformat()})"
    # One view request across all platforms; never retry by individual platform.
    return await _query(f"{settings.gtfs_url}arrivals_departures", query)
