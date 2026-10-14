import asyncio
import re
import time
from typing import Any

from cachetools import TTLCache

from ..config import settings
from ..models import BBox, Location, LocationInput
from .http import SourceError, http

_cache: TTLCache[str, Location] = TTLCache(maxsize=512, ttl=settings.geocode_ttl)
_bbox_cache: TTLCache[str, BBox] = TTLCache(maxsize=512, ttl=settings.geocode_ttl)
_region_code_cache: TTLCache[str, str | None] = TTLCache(
    maxsize=512, ttl=settings.geocode_ttl
)
_lock = asyncio.Lock()
_last_request = 0.0

_GAZETTEER = {
    "weinsberger kreuz": Location(
        lat=49.1566648,
        lon=9.3057553,
        label="Kreuz Weinsberg, A 6, Weinsberg, Baden-Württemberg, Deutschland",
        type="motorway_junction",
    ),
    "kreuz weinsberg": Location(
        lat=49.1566648,
        lon=9.3057553,
        label="Kreuz Weinsberg, A 6, Weinsberg, Baden-Württemberg, Deutschland",
        type="motorway_junction",
    ),
    "heilbronn hbf": Location(
        lat=49.1431403,
        lon=9.2076637,
        label="Heilbronn Hauptbahnhof, Heilbronn, Baden-Württemberg, Deutschland",
        type="station",
    ),
    "stuttgart hbf": Location(
        lat=48.7856099,
        lon=9.1833959,
        label="Stuttgart Hauptbahnhof, Stuttgart, Baden-Württemberg, Deutschland",
        type="station",
    ),
    "heilbronn city centre": Location(
        lat=49.1422910,
        lon=9.2186550,
        label="Heilbronn, Baden-Württemberg, Deutschland",
        type="city",
    ),
}
for _alias in (
    "heilbronn city center",
    "heilbronn innenstadt",
    "heilbronner innenstadt",
    "heilbronn zentrum",
):
    _GAZETTEER[_alias] = _GAZETTEER["heilbronn city centre"]

_JUNCTION_WORDS = re.compile(r"\b(kreuz|dreieck|anschlussstelle)\b", re.IGNORECASE)
_CENTRE_WORDS = re.compile(
    r"\b(?:innenstadt|zentrum|city\s+cent(?:er|re))\b", re.IGNORECASE
)


async def _request(url: str, params: dict[str, Any]) -> Any:
    global _last_request
    async with _lock:
        wait_seconds = 1.0 - (time.monotonic() - _last_request)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        payload = await http.get_json(url, params)
        _last_request = time.monotonic()
        return payload


def _location(result: dict[str, Any]) -> Location:
    return Location(
        lat=float(result["lat"]),
        lon=float(result["lon"]),
        label=result.get("display_name"),
        type=result.get("type"),
    )


async def _linked_centre(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("category") == "place" and result.get("type") in {"city", "town"}:
        return result
    osm_type = str(result.get("osm_type", ""))[:1].upper()
    osm_id = result.get("osm_id")
    if not osm_type or osm_id is None:
        return result
    base_url = settings.nominatim_url.rsplit("/", 1)[0]
    details = await _request(
        f"{base_url}/details",
        {
            "format": "json",
            "osmtype": osm_type,
            "osmid": osm_id,
            "linkedplaces": 1,
        },
    )
    linked = next(
        (
            place
            for place in details.get("linked_places", [])
            if place.get("class") == "place" and place.get("type") in {"city", "town"}
        ),
        None,
    )
    if linked is None:
        return result
    lookup = await _request(
        f"{base_url}/lookup",
        {
            "format": "jsonv2",
            "osm_ids": f"{linked['osm_type']}{linked['osm_id']}",
            "addressdetails": 1,
        },
    )
    return lookup[0] if lookup else result


async def resolve(location: LocationInput | dict[str, Any]) -> Location:
    if isinstance(location, Location):
        return location
    if isinstance(location, dict):
        return Location.model_validate(location)
    key = location.strip().casefold()
    if not key:
        raise ValueError("location must not be empty")
    if key in _GAZETTEER:
        return _GAZETTEER[key].model_copy(deep=True)
    if key in _cache:
        return _cache[key]
    centre_match = _CENTRE_WORDS.search(location)
    query = _CENTRE_WORDS.sub("", location).strip(" ,-") if centre_match else location
    payload = await _request(
        settings.nominatim_url,
        {
            "format": "jsonv2",
            "q": query,
            "countrycodes": "de",
            "viewbox": "7.5,49.8,10.6,47.5",
            "bounded": 1,
            "limit": 10,
            "dedupe": 0,
        },
    )
    if not payload:
        raise SourceError(f"Could not geocode location: {location}")
    selected = payload[0]
    if _JUNCTION_WORDS.search(location):
        selected = next(
            (item for item in payload if item.get("type") == "motorway_junction"),
            selected,
        )
    elif centre_match:
        place_node = next(
            (
                item
                for item in payload
                if item.get("category") == "place" and item.get("type") in {"city", "town"}
            ),
            None,
        )
        selected = place_node or await _linked_centre(selected)
    result = _location(selected)
    _cache[key] = result
    return result


async def resolve_region(place: str) -> tuple[Location, BBox, str | None]:
    key = place.strip().casefold()
    if not key:
        raise ValueError("region must not be empty")
    if key in _cache and key in _bbox_cache and key in _region_code_cache:
        return _cache[key], _bbox_cache[key], _region_code_cache[key]
    payload = await _request(
        settings.nominatim_url,
        {
            "format": "jsonv2",
            "q": f"{place}, Baden-Württemberg",
            "countrycodes": "de",
            "viewbox": "7.5,49.8,10.6,47.5",
            "bounded": 1,
            "limit": 1,
            "addressdetails": 1,
            "extratags": 1,
        },
    )
    if not payload or not payload[0].get("boundingbox"):
        raise SourceError(f"Could not geocode region: {place}")
    south, north, west, east = (float(value) for value in payload[0]["boundingbox"])
    location = Location(
        lat=float(payload[0]["lat"]),
        lon=float(payload[0]["lon"]),
        label=payload[0].get("display_name"),
        type=payload[0].get("type"),
    )
    bbox = BBox(min_lat=south, min_lon=west, max_lat=north, max_lon=east)
    official_region_code = payload[0].get("extratags", {}).get(
        "de:regionalschluessel"
    )
    _cache[key] = location
    _bbox_cache[key] = bbox
    _region_code_cache[key] = official_region_code
    return location, bbox, official_region_code


async def resolve_bbox(place: str) -> tuple[Location, BBox]:
    location, bbox, _official_region_code = await resolve_region(place)
    return location, bbox