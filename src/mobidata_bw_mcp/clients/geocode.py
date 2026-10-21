import asyncio
import json
import re
import time
from difflib import SequenceMatcher
from typing import Any

from cachetools import TTLCache

from ..config import settings
from ..geo import haversine_m
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
    "weinsberger kreuz a6/a81",
    "weinsberger kreuz a 6/a 81",
    "kreuz weinsberg a6/a81",
):
    _GAZETTEER[_alias] = _GAZETTEER["weinsberger kreuz"]
for _alias in (
    "heilbronn city center",
    "heilbronn innenstadt",
    "heilbronner innenstadt",
    "heilbronn zentrum",
):
    _GAZETTEER[_alias] = _GAZETTEER["heilbronn city centre"]

# Address verified against https://www.memox.com/standorte/stuttgart/.
# Resolve the street address rather than inventing or hard-coding venue coordinates.
_ADDRESS_GAZETTEER = {
    "memox stuttgart": "Theodor-Heuss-Straße 2, Stuttgart",
}


class LocationClarification(SourceError):
    """Carry bounded place choices through MCP's textual tool-error response."""

    def __init__(self, query: str, suggestions: list[dict[str, str]]) -> None:
        super().__init__(json.dumps({
            "error": "location_clarification", "query": query,
            "suggestions": suggestions[:3],
        }, ensure_ascii=False))


def gazetteer_suggestions(query: str) -> list[dict[str, str]]:
    key = query.strip().casefold()
    ranked = []
    for name in [*_GAZETTEER, *_ADDRESS_GAZETTEER]:
        ratio = SequenceMatcher(None, key, name).ratio()
        if ratio >= 0.72 or (len(key) >= 5 and key in name):
            if name in _ADDRESS_GAZETTEER:
                address = _ADDRESS_GAZETTEER[name]
                label = f"{name.split()[0]}, {address}"
                location = address
            else:
                label = _GAZETTEER[name].label or name
                location = name
            ranked.append((ratio, {"label": label, "location": location}))
    choices = []
    for _, option in sorted(ranked, key=lambda pair: pair[0], reverse=True):
        if option not in choices:
            choices.append(option)
    return choices[:3]


async def _suggestions(query: str) -> list[dict[str, str]]:
    choices = gazetteer_suggestions(query)
    if choices:
        return choices
    # Broaden partial names without silently substituting a city for a venue.
    words = query.replace(",", " ").split()
    queries = [" ".join(words[:-1]), words[-1]] if len(words) > 1 else []
    for partial in dict.fromkeys(queries):
        try:
            payload = await _request(settings.nominatim_url, {
                "format": "jsonv2", "q": partial, "countrycodes": "de",
                "viewbox": "7.5,49.8,10.6,47.5", "bounded": 1, "limit": 3,
            })
        except SourceError:
            continue
        for item in payload:
            label = item.get("display_name")
            if label and not any(option["label"] == label for option in choices):
                choices.append({"label": label, "location": label})
        if len(choices) >= 3:
            break
    return choices[:3]


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
    if key in _ADDRESS_GAZETTEER:
        result = await resolve(_ADDRESS_GAZETTEER[key])
        return result.model_copy(update={"label": f"memox, {_ADDRESS_GAZETTEER[key]}"})
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
        raise LocationClarification(location, await _suggestions(location))
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
    if not centre_match and not _JUNCTION_WORDS.search(location):
        alternatives = [selected]
        for item in payload:
            if item.get("type") == selected.get("type") and all(
                haversine_m(float(item["lat"]), float(item["lon"]),
                            float(other["lat"]), float(other["lon"])) > 500
                for other in alternatives
            ):
                alternatives.append(item)
        if len(alternatives) > 1:
            raise LocationClarification(location, [
                {"label": item["display_name"], "location": item["display_name"]}
                for item in alternatives[:3] if item.get("display_name")
            ])
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