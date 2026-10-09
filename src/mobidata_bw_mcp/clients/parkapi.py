from typing import Any

from ..config import settings
from .http import http


async def parking_sites(params: dict[str, Any], limit: int) -> tuple[list[dict[str, Any]], int]:
    requested = min(limit, settings.max_limit)
    payload = await http.get_json(
        f"{settings.parkapi_url}parking-sites",
        {"ignore_duplicates": True, **params, "limit": requested},
    )
    return payload.get("items", []), int(payload.get("total_count", 0))


async def all_parking_sites(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    url = f"{settings.parkapi_url}parking-sites"
    query: dict[str, Any] = {
        "ignore_duplicates": True,
        **(params or {}),
        "limit": settings.max_limit,
    }
    items: list[dict[str, Any]] = []
    while True:
        payload = await http.get_json(url, query)
        items.extend(payload.get("items", []))
        next_id = payload.get("next_id")
        if next_id is None:
            return items
        query["start"] = next_id


async def sources() -> dict[str, Any]:
    return await http.get_json(f"{settings.parkapi_url}sources")