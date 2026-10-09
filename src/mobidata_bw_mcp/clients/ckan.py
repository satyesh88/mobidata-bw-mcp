from typing import Any

from cachetools import TTLCache

from ..config import settings
from .http import SourceError, http

_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=256, ttl=settings.ckan_ttl)


async def _action(name: str, params: dict[str, Any]) -> dict[str, Any]:
    key = f"{name}:{sorted(params.items())}"
    if key in _cache:
        return _cache[key]
    payload = await http.get_json(f"{settings.ckan_url}{name}", params)
    if not payload.get("success"):
        raise SourceError(f"CKAN action {name} did not succeed")
    _cache[key] = payload["result"]
    return payload["result"]


async def search(query: str, limit: int) -> dict[str, Any]:
    return await _action("package_search", {"q": query, "rows": limit})


async def get(dataset_id: str) -> dict[str, Any]:
    return await _action("package_show", {"id": dataset_id})