import pytest

from mobidata_bw_mcp.clients import parkapi
from mobidata_bw_mcp.models import BBox, Location
from mobidata_bw_mcp.server import lifespan
from mobidata_bw_mcp.tools import discovery, health, parking, sharing


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
async def test_health_reports_no_data_instead_of_zero_percent(monkeypatch) -> None:
    async def fake_bbox(region):
        return Location(lat=49.14, lon=9.21), BBox(
            min_lat=49.1, min_lon=9.1, max_lat=49.2, max_lon=9.3
        )

    async def no_parking(params):
        return []

    monkeypatch.setattr(health.geocode, "resolve_bbox", fake_bbox)
    monkeypatch.setattr(health.parkapi, "all_parking_sites", no_parking)

    result = await health.data_health("Empty City", "parking")

    assert result["items"][0]["status"] == "no_data"
    assert result["items"][0]["live_percent"] is None
    assert "no data found" in result["warnings"][0]


@pytest.mark.asyncio
async def test_parking_deduplicates_and_warns_without_clamping(monkeypatch) -> None:
    async def fake_resolve(location):
        return Location(lat=49.1427, lon=9.2069)

    async def fake_sites(params, limit):
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
            2,
        )

    monkeypatch.setattr(parking.geocode, "resolve", fake_resolve)
    monkeypatch.setattr(parking.parkapi, "parking_sites", fake_sites)

    result = await parking.find_parking({"lat": 49.1427, "lon": 9.2069})

    assert result["count"] == 1
    assert result["items"][0]["free_now"] == 315
    assert any("exceed capacity" in warning for warning in result["warnings"])
    assert any("duplicate" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_sharing_separates_virtual_inventory_and_computes_battery(monkeypatch) -> None:
    async def fake_resolve(location):
        return Location(lat=49.14, lon=9.21)

    async def fake_features(layer, **kwargs):
        properties = (
            {
                "feed_id": "dott_heilbronn",
                "name": "Mobility Hub",
                "is_virtual_station": True,
                "num_scooters_available": 5,
                "last_reported": "2026-10-10T10:00:00Z",
            }
            if layer.endswith("sharing_stations")
            else {
                "feed_id": "dott_heilbronn",
                "form_factor": "scooter",
                "current_range_meters": 15_000,
                "max_range_meters": 30_000,
                "last_reported": "2026-10-10T10:00:00Z",
            }
        )
        return {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [9.21, 49.14]},
                    "properties": properties,
                }
            ]
        }

    monkeypatch.setattr(sharing.geocode, "resolve", fake_resolve)
    monkeypatch.setattr(sharing.wfs, "features", fake_features)

    result = await sharing.find_sharing({"lat": 49.14, "lon": 9.21})
    virtual, vehicle = result["items"]

    assert "available" not in virtual
    assert virtual["virtual_station_inventory"]["scooter"] == 5
    assert virtual["count_semantics"] == "virtual_station_inventory"
    assert vehicle["battery_pct"] == 50.0


@pytest.mark.asyncio
async def test_catalog_flags_missing_licence(monkeypatch) -> None:
    async def fake_search(query, limit):
        return {
            "count": 1,
            "results": [{"title": "Nextbike", "name": "nextbike", "resources": []}],
        }

    monkeypatch.setattr(discovery.ckan, "search", fake_search)

    result = await discovery.search_datasets("Fahrrad")

    assert result["items"][0]["licence_missing"] is True
    assert "Nextbike" in result["warnings"][0]


@pytest.mark.asyncio
async def test_lifespan_preloads_sign_index(monkeypatch) -> None:
    called = False

    async def fake_sign_index():
        nonlocal called
        called = True

    monkeypatch.setattr("mobidata_bw_mcp.server.signs.sign_index", fake_sign_index)

    async with lifespan(None):
        assert called is True