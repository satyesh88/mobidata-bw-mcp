from copy import deepcopy
from typing import Any

from cachetools import TTLCache

from ..config import settings
from .http import http

_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=256, ttl=settings.realtime_ttl)


async def _parking_payload(params: dict[str, Any]) -> dict[str, Any]:
    key = repr(sorted(params.items()))
    if key not in _cache:
        _cache[key] = await http.get_json(f"{settings.parkapi_url}parking-sites", params)
    return deepcopy(_cache[key])


async def parking_sites(
    params: dict[str, Any], limit: int
) -> tuple[list[dict[str, Any]], int, int | None]:
    requested = min(limit, settings.max_limit)
    payload = await _parking_payload({"ignore_duplicates": True, **params, "limit": requested})
    return (
        payload.get("items", []),
        int(payload.get("total_count", 0)),
        payload.get("next_id"),
    )


async def all_parking_sites(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {
        "ignore_duplicates": True,
        **(params or {}),
        "limit": settings.max_limit,
    }
    items: list[dict[str, Any]] = []
    while True:
        payload = await _parking_payload(query)
        items.extend(payload.get("items", []))
        next_id = payload.get("next_id")
        if next_id is None:
            return items
        query["start"] = next_id


async def sources() -> dict[str, Any]:
    return await http.get_json(f"{settings.parkapi_url}sources")


async def nearest_parking_sites(
    params: dict[str, Any], radius_m: int, cap: int = 1000
) -> tuple[list[dict[str, Any]], int]:
    """Fetch every site in a radius, shrinking dense areas so the nearest sites are complete."""
    radius = radius_m
    for _ in range(4):
        _items, total, _next = await parking_sites({**params, "radius": radius}, 1)
        if total <= cap:
            break
        radius = max(50, round(radius * (cap * 0.8 / total) ** 0.5))
    return await all_parking_sites({**params, "radius": radius}), radius
