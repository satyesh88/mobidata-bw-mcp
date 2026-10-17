"""Read-only diagnostic; run with the server venv and PYTHONPATH pointing at src."""
import asyncio
import json
import logging
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from mobidata_bw_mcp.clients import gtfs
from mobidata_bw_mcp.clients.http import http
from mobidata_bw_mcp.tools import transit


async def main() -> None:
    original_json = http.get_json
    original_lookup = getattr(gtfs, "resolve_stop_ids", None)
    print(json.dumps({"module": transit.__file__}), flush=True)

    async def query(url, params=None, **kwargs):
        started = time.perf_counter()
        outcome = "ok"
        try:
            return await original_json(url, params, **kwargs)
        except BaseException as exc:
            outcome = type(exc).__name__
            raise
        finally:
            # Diagnostic inputs are fixed below. Never print headers or API keys.
            print(json.dumps({
                "step": "query", "resource": urlparse(url).path.rsplit("/", 1)[-1],
                "stop_filter": (params or {}).get("stop_id"),
                "limit": (params or {}).get("limit"),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "outcome": outcome,
            }), flush=True)

    async def lookup(value):
        started = time.perf_counter()
        ids = []
        try:
            ids = await original_lookup(value)
            return ids
        finally:
            print(json.dumps({
                "step": "stop_lookup", "stop_id_count": len(ids),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }), flush=True)

    http.get_json = query
    if original_lookup is not None:
        gtfs.resolve_stop_ids = lookup
    else:
        print(json.dumps({
            "step": "stop_lookup", "stop_id_count": 0, "duration_ms": 0,
            "note": "installed version has no name-to-ID lookup",
        }), flush=True)
    for label in (("cold", "cached") if original_lookup else ("cold",)):
        started = time.perf_counter()
        outcome = {}
        try:
            result = await transit.get_departures(
                "Heilbronn Hbf",
                from_time=datetime(2026, 10, 19, 9, tzinfo=ZoneInfo("Europe/Berlin")),
                limit=10,
            )
            outcome = {"count": result.get("count"), "error": result.get("error")}
        except Exception as exc:
            outcome = {"error": type(exc).__name__}
        finally:
            print(json.dumps({
                "step": "total", "run": label, **outcome,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }), flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
