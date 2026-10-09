from typing import Any

from cachetools import TTLCache

from ..config import settings
from .http import http

_roadworks: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1, ttl=settings.roadworks_ttl)
_signs: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=1, ttl=settings.signs_ttl)


async def roadworks() -> dict[str, Any]:
    if "data" not in _roadworks:
        _roadworks["data"] = await http.get_json(settings.roadworks_url)
    return _roadworks["data"]


async def signs() -> dict[str, Any]:
    if "data" not in _signs:
        _signs["data"] = await http.get_json(settings.signs_url, timeout=120)
    return _signs["data"]