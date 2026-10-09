from typing import Any

from ..config import settings
from .http import http


async def departures(params: dict[str, Any]) -> list[dict[str, Any]]:
    return await http.get_json(f"{settings.gtfs_url}arrivals_departures", params)