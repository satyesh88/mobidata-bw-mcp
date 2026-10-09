import asyncio
import time
from typing import Any

from cachetools import TTLCache

from ..config import settings
from ..models import BBox, Location, LocationInput
from .http import SourceError, http

_cache: TTLCache[str, Location] = TTLCache(maxsize=512, ttl=settings.geocode_ttl)
_bbox_cache: TTLCache[str, BBox] = TTLCache(maxsize=512, ttl=settings.geocode_ttl)
_lock = asyncio.Lock()
_last_request = 0.0


async def resolve(location: LocationInput | dict[str, Any]) -> Location:
    global _last_request
    if isinstance(location, Location):
        return location
    if isinstance(location, dict):
        return Location.model_validate(location)
    key = location.strip().casefold()
    if not key:
        raise ValueError("location must not be empty")
    if key in _cache:
        return _cache[key]
    async with _lock:
        wait_seconds = 1.0 - (time.monotonic() - _last_request)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        payload = await http.get_json(
            settings.nominatim_url,
            {
                "format": "jsonv2",
                "q": location,
                "countrycodes": "de",
                "viewbox": "7.5,49.8,10.6,47.5",
                "bounded": 1,
                "limit": 1,
            },
        )
        _last_request = time.monotonic()
    if not payload:
        raise SourceError(f"Could not geocode location: {location}")
    result = Location(
        lat=float(payload[0]["lat"]),
        lon=float(payload[0]["lon"]),
        label=payload[0].get("display_name"),
    )
    _cache[key] = result
    return result


async def resolve_bbox(place: str) -> tuple[Location, BBox]:
    global _last_request
    key = place.strip().casefold()
    if not key:
        raise ValueError("region must not be empty")
    if key in _cache and key in _bbox_cache:
        return _cache[key], _bbox_cache[key]
    async with _lock:
        wait_seconds = 1.0 - (time.monotonic() - _last_request)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        payload = await http.get_json(
            settings.nominatim_url,
            {
                "format": "jsonv2",
                "q": f"{place}, Baden-Württemberg",
                "countrycodes": "de",
                "viewbox": "7.5,49.8,10.6,47.5",
                "bounded": 1,
                "limit": 1,
            },
        )
        _last_request = time.monotonic()
    if not payload or not payload[0].get("boundingbox"):
        raise SourceError(f"Could not geocode region: {place}")
    south, north, west, east = (float(value) for value in payload[0]["boundingbox"])
    location = Location(
        lat=float(payload[0]["lat"]),
        lon=float(payload[0]["lon"]),
        label=payload[0].get("display_name"),
    )
    bbox = BBox(min_lat=south, min_lon=west, max_lat=north, max_lon=east)
    _cache[key] = location
    _bbox_cache[key] = bbox
    return location, bbox