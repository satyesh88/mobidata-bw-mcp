import asyncio
import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """A source request failed with a client-safe message."""


class HttpClient:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._client = httpx.AsyncClient(
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            timeout=settings.timeout_seconds,
            follow_redirects=True,
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        async with self._semaphore:
            for attempt in range(2):
                try:
                    response = await self._client.request(
                        method, url, params=params, timeout=timeout or settings.timeout_seconds
                    )
                    response.raise_for_status()
                    return response
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    if attempt == 0 and not (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code < 500
                    ):
                        await asyncio.sleep(0.35)
                        continue
                    logger.exception("Source request failed: %s", url)
                    raise SourceError(f"MobiData source request failed for {url}") from exc
        raise SourceError(f"MobiData source request failed for {url}")

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        response = await self.request("GET", url, params=params, timeout=timeout)
        try:
            return response.json()
        except ValueError as exc:
            logger.exception("Invalid JSON from %s", url)
            raise SourceError(f"MobiData source returned invalid JSON for {url}") from exc

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return (await self.request("GET", url, params=params)).text


http = HttpClient()