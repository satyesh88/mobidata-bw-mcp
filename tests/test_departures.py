import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from mobidata_bw_mcp.clients import gtfs
from mobidata_bw_mcp.tools import transit

WHEN = datetime(2026, 10, 19, 9, tzinfo=ZoneInfo("Europe/Berlin"))


@pytest.fixture(autouse=True)
def empty_caches():
    gtfs._stop_cache.clear()
    gtfs._departure_cache.clear()
    yield
    gtfs._stop_cache.clear()
    gtfs._departure_cache.clear()


async def test_departure_cache_hit_under_100ms_and_exact_windows(monkeypatch):
    async def slow(params):
        await asyncio.sleep(0.15)
        return [{"t_departure": "2026-10-19T09:12:00+02:00", "stop_name": "Heilbronn Hbf"}]

    lookup = AsyncMock(return_value=["de:08121:26"])
    source = AsyncMock(side_effect=slow)
    monkeypatch.setattr(gtfs, "resolve_stop_ids", lookup)
    monkeypatch.setattr(gtfs, "departures", source)
    first = await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    began = time.perf_counter()
    cached = await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    assert time.perf_counter() - began < 0.1
    assert first["items"] == cached["items"]
    assert source.await_count == 1
    params = source.await_args.args[0]
    assert params["limit"] == 10
    assert "09:00:00" in params["and"] and "10:30:00" in params["and"]
    assert params["select"] == gtfs.COLUMNS
    # Neither later minutes nor larger limits may reuse a truncated earlier window.
    await transit.get_departures("Heilbronn Hbf", from_time=WHEN.replace(minute=45), limit=200)
    assert source.await_count == 2
    assert source.await_args.args[0]["limit"] == 20


async def test_stop_lookup_cached_and_parent_expanded(monkeypatch):
    source = AsyncMock(side_effect=[
        [{"stop_id": "de:1_Parent", "parent_station": None},
         {"stop_id": "de:1", "parent_station": "de:1_Parent"}],
        [{"stop_id": "de:1"}, {"stop_id": "de:1:2"}],
    ])
    monkeypatch.setattr(gtfs.http, "get_json", source)
    assert await gtfs.resolve_stop_ids("Heilbronn Hbf") == [
        "de:1_Parent", "de:1", "de:1:2"
    ]
    assert await gtfs.resolve_stop_ids("heilbronn hbf") == [
        "de:1_Parent", "de:1", "de:1:2"
    ]
    assert source.await_count == 2
    assert source.await_args_list[0].args[1]["stop_name"] == "ilike.Heilbronn Hauptbahnhof"


async def test_candidate_trips_narrow_view_and_keep_midnight_times(monkeypatch):
    source = AsyncMock(side_effect=[
        [{"trip_id": "overnight"}],  # previous service day's 47:30
        [{"trip_id": "today"}],
        [{"trip_id": "tomorrow"}],
        [{"t_departure": "2026-10-20T00:15:00+02:00", "stop_id": "de:1"}],
    ])
    monkeypatch.setattr(gtfs.http, "get_json", source)
    params = {
        "_start": WHEN.replace(hour=23, minute=30).isoformat(),
        "stop_id": 'in.("de:1")', "date": "eq.2026-10-19",
        "select": gtfs.COLUMNS, "limit": 10, "order": "t_departure",
        "and": "(t_departure.gte.2026-10-19T23:30:00+02:00,"
               "t_departure.lt.2026-10-20T01:00:00+02:00)",
    }
    result = await gtfs.departures(params)
    assert len(result) == 1
    calls = source.await_args_list
    assert "47:30:00" in calls[0].args[1]["and"]
    assert "00:00:00" in calls[2].args[1]["and"]
    view = calls[-1].args[1]
    assert view["trip_id"] == 'in.("overnight","today","tomorrow")'
    assert view["select"] == gtfs.COLUMNS
    assert "_start" not in view
    assert view["date"] == "gte.2026-10-18"
    assert "date.lte.2026-10-20" in view["and"]


async def test_source_failure_is_not_cached(monkeypatch):
    monkeypatch.setattr(gtfs, "resolve_stop_ids", AsyncMock(return_value=["de:1"]))
    source = AsyncMock(side_effect=[TimeoutError(), []])
    monkeypatch.setattr(gtfs, "departures", source)
    with pytest.raises(TimeoutError):
        await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    assert source.await_count == 2


async def test_stop_lookup_expires_after_24_hours(monkeypatch):
    from cachetools import TTLCache

    now = [0.0]
    monkeypatch.setattr(gtfs, "_stop_cache", TTLCache(
        maxsize=10, ttl=86400, timer=lambda: now[0]
    ))
    source = AsyncMock(return_value=[{"stop_id": "de:1", "parent_station": None}])
    monkeypatch.setattr(gtfs.http, "get_json", source)
    await gtfs.resolve_stop_ids("Heilbronn Hbf")
    now[0] = 86399
    await gtfs.resolve_stop_ids("Heilbronn Hbf")
    assert source.await_count == 1
    now[0] = 86401
    await gtfs.resolve_stop_ids("Heilbronn Hbf")
    assert source.await_count == 2


async def test_departure_cache_expires_after_ten_minutes(monkeypatch):
    from cachetools import TTLCache

    now = [0.0]
    monkeypatch.setattr(gtfs, "_departure_cache", TTLCache(
        maxsize=10, ttl=600, timer=lambda: now[0]
    ))
    monkeypatch.setattr(gtfs, "resolve_stop_ids", AsyncMock(return_value=["de:1"]))
    source = AsyncMock(return_value=[])
    monkeypatch.setattr(gtfs, "departures", source)
    await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    now[0] = 599
    await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    assert source.await_count == 1
    now[0] = 601
    await transit.get_departures("Heilbronn Hbf", from_time=WHEN)
    assert source.await_count == 2
