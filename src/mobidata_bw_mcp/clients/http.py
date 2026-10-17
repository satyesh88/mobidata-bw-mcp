import asyncio
import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """A source request failed with a client-safe message."""


class SourceTimeout(SourceError):
    """The upstream source did not respond in time."""


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
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        timeout: float | None = None,
        attempts: int = 2,
    ) -> httpx.Response:
        async with self._semaphore:
            for attempt in range(attempts):
                try:
                    response = await self._client.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        json=json_body,
                        timeout=timeout or settings.timeout_seconds,
                    )
                    response.raise_for_status()
                    return response
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    if attempt + 1 < attempts and not (
                        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500
                    ):
                        await asyncio.sleep(0.35)
                        continue
                    # No traceback: httpx errors embed the full URL, including user locations.
                    logger.warning("Source request failed: %s (%s)", url, type(exc).__name__)
                    error_type = (
                        SourceTimeout
                        if (
                            isinstance(exc, httpx.TimeoutException)
                            or isinstance(exc, httpx.HTTPStatusError)
                            and exc.response.status_code in {408, 504}
                        )
                        else SourceError
                    )
                    raise error_type(f"MobiData source request failed for {url}") from exc
        raise SourceError(f"MobiData source request failed for {url}")

    async def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        attempts: int = 2,
    ) -> Any:
        response = await self.request("GET", url, params=params, timeout=timeout, attempts=attempts)
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("Invalid JSON from %s", url)
            raise SourceError(f"MobiData source returned invalid JSON for {url}") from exc

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return (await self.request("GET", url, params=params)).text


http = HttpClient()
