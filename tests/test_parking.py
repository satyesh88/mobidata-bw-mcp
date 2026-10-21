import pytest

from mobidata_bw_mcp.clients import parkapi
from mobidata_bw_mcp.models import Location
from mobidata_bw_mcp.tools import parking


@pytest.mark.asyncio
async def test_parking_pagination_preserves_filters(monkeypatch) -> None:
    calls = []

    async def fake_get_json(url, params):
        calls.append(dict(params))
        if len(calls) == 1:
            return {"items": [{"id": 1}], "next_id": 42}
        return {"items": [{"id": 2}], "next_id": None}

    monkeypatch.setattr(parkapi.http, "get_json", fake_get_json)

    records = await parkapi.all_parking_sites({"lat_min": 49.0, "lat_max": 50.0})

    assert [record["id"] for record in records] == [1, 2]
    assert calls[1]["start"] == 42
    assert calls[1]["lat_min"] == 49.0
    assert calls[1]["ignore_duplicates"] is True





@pytest.mark.asyncio
async def test_parking_deduplicates_and_warns_without_clamping(monkeypatch) -> None:
    async def fake_resolve(location):
        return Location(lat=49.1427, lon=9.2069)

    async def fake_sites(params, radius_m):
        return (
            [
                {
                    "id": 1,
                    "name": "Cityparkhaus am Bollwerksturm",
                    "lat": 49.14636,
                    "lon": 9.21611,
                    "capacity": 304,
                    "has_realtime_data": False,
                },
                {
                    "id": 2,
                    "name": "Heilbronn, Bollwerksturm",
                    "lat": 49.14637,
                    "lon": 9.21612,
                    "capacity": 304,
                    "realtime_free_capacity": 315,
                    "has_realtime_data": True,
                    "realtime_data_updated_at": "2026-10-10T10:00:00Z",
                },
            ],
            radius_m,
        )

    monkeypatch.setattr(parking.geocode, "resolve", fake_resolve)
    monkeypatch.setattr(parking.parkapi, "nearest_parking_sites", fake_sites)

    result = await parking.find_parking({"lat": 49.1427, "lon": 9.2069})

    assert result["count"] == 1
    assert result["items"][0]["free_now"] == 315
    assert any("exceed capacity" in warning for warning in result["warnings"])
    assert any("duplicate" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_parking_returns_nearest_first_across_pages(monkeypatch) -> None:
    async def fake_resolve(location):
        return Location(lat=49.0, lon=9.0)

    # ParkAPI order is not distance order: the nearest sites come last.
    sites = [
        {"id": index, "name": f"Site {index}", "lat": 49.0 + offset, "lon": 9.0, "capacity": index}
        for index, offset in enumerate([0.009, 0.006, 0.003, 0.001], start=1)
    ]

    async def fake_sites(params, radius_m):
        return sites, radius_m

    monkeypatch.setattr(parking.geocode, "resolve", fake_resolve)
    monkeypatch.setattr(parking.parkapi, "nearest_parking_sites", fake_sites)

    first = await parking.find_parking({"lat": 49.0, "lon": 9.0}, radius_m=2000, limit=2)
    assert [item["id"] for item in first["items"]] == [4, 3]
    assert first["truncated"] is True
    assert first["next_cursor"] == 2

    second = await parking.find_parking(
        {"lat": 49.0, "lon": 9.0}, radius_m=2000, limit=2, cursor=first["next_cursor"]
    )
    assert [item["id"] for item in second["items"]] == [2, 1]
    assert second["truncated"] is False
    assert second.get("next_cursor") is None
    assert second["query"]["cursor"] == 2


@pytest.mark.asyncio
async def test_parking_warns_when_dense_area_radius_was_reduced(monkeypatch) -> None:
    async def fake_resolve(location):
        return Location(lat=49.0, lon=9.0)

    async def fake_sites(params, radius_m):
        return [{"id": 1, "name": "A", "lat": 49.0005, "lon": 9.0, "capacity": 1}], 400

    monkeypatch.setattr(parking.geocode, "resolve", fake_resolve)
    monkeypatch.setattr(parking.parkapi, "nearest_parking_sites", fake_sites)

    result = await parking.find_parking({"lat": 49.0, "lon": 9.0}, radius_m=3000)

    assert any("nearest 400 m of the requested 3000 m" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_nearest_parking_sites_shrinks_dense_radius(monkeypatch) -> None:
    probes = []

    async def fake_sites(params, limit):
        probes.append(params["radius"])
        return [], (5000 if params["radius"] > 1500 else 700), None

    async def fake_all(params):
        probes.append(("all", params["radius"]))
        return [{"id": 1}]

    monkeypatch.setattr(parkapi, "parking_sites", fake_sites)
    monkeypatch.setattr(parkapi, "all_parking_sites", fake_all)

    records, radius = await parkapi.nearest_parking_sites({"lat": 1, "lon": 2}, 3000)

    assert records == [{"id": 1}]
    assert radius < 3000
    assert probes[-1] == ("all", radius)


@pytest.mark.asyncio
async def test_nearest_parking_sites_keeps_radius_when_area_is_small(monkeypatch) -> None:
    async def fake_sites(params, limit):
        return [], 40, None

    async def fake_all(params):
        return []

    monkeypatch.setattr(parkapi, "parking_sites", fake_sites)
    monkeypatch.setattr(parkapi, "all_parking_sites", fake_all)

    _records, radius = await parkapi.nearest_parking_sites({}, 800)

    assert radius == 800

