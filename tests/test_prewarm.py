import logging
from unittest.mock import AsyncMock

import pytest

from mobidata_bw_mcp import prewarm
from mobidata_bw_mcp.clients import parkapi
from mobidata_bw_mcp.server import lifespan


async def test_prewarm_all_sources_and_survives_one_failure(monkeypatch, caplog):
    table = AsyncMock()
    stops = AsyncMock()
    parking = AsyncMock(side_effect=[RuntimeError("offline"), None])
    signs = AsyncMock()
    monkeypatch.setattr(prewarm.bfrk, "table", table)
    monkeypatch.setattr(prewarm.gtfs, "resolve_stop_ids", stops)
    monkeypatch.setattr(prewarm, "_parking", parking)
    monkeypatch.setattr(prewarm.signs, "sign_index", signs)
    with caplog.at_level(logging.INFO):
        await prewarm.prewarm()
    assert table.await_count == 16
    assert {call.args[0] for call in stops.await_args_list} == {"Heilbronn Hbf", "Stuttgart Hbf"}
    assert parking.await_count == 2
    signs.assert_awaited_once()
    assert "prewarm done in" in caplog.text


async def test_parkapi_warmed_payload_reused_and_not_mutated(monkeypatch):
    parkapi._cache.clear()
    source = AsyncMock(return_value={"items": [{"name": "Bahnhof West"}], "total_count": 1})
    monkeypatch.setattr(parkapi.http, "get_json", source)
    params = {"lat": 49.14, "lon": 9.2, "purpose": "CAR", "radius": 1000}
    first, _, _ = await parkapi.parking_sites(params, 1)
    first[0]["name"] = "changed"
    second, _, _ = await parkapi.parking_sites(params, 1)
    assert second[0]["name"] == "Bahnhof West"
    source.assert_awaited_once()
    parkapi._cache.clear()


@pytest.mark.asyncio
async def test_lifespan_prewarms_without_blocking_startup(monkeypatch) -> None:
    import asyncio

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def warm():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr("mobidata_bw_mcp.server.prewarm", warm)
    async with lifespan(None):
        await asyncio.wait_for(started.wait(), 0.1)
    assert cancelled.is_set()
