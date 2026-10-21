from datetime import UTC, datetime, timedelta

import pytest

from mobidata_bw_mcp.models import BBox, Location
from mobidata_bw_mcp.tools import health


@pytest.mark.asyncio
async def test_health_reports_no_data_instead_of_zero_percent(monkeypatch) -> None:
    async def fake_region(region):
        return (
            Location(lat=49.14, lon=9.21),
            BBox(min_lat=49.1, min_lon=9.1, max_lat=49.2, max_lon=9.3),
            "081210000000",
        )

    async def no_parking(params):
        return []

    monkeypatch.setattr(health.geocode, "resolve_region", fake_region)
    monkeypatch.setattr(health.parkapi, "all_parking_sites", no_parking)

    result = await health.data_health("Empty City", "parking")

    assert result["items"][0]["status"] == "no_data"
    assert result["items"][0]["live_percent"] is None
    assert "no data found" in result["warnings"][0]



@pytest.mark.asyncio
async def test_health_uses_city_code_for_wfs_datasets(monkeypatch) -> None:
    async def fake_region(region):
        return (
            Location(lat=48.78, lon=9.18, label="Stuttgart"),
            BBox(min_lat=48.69, min_lon=9.03, max_lat=48.87, max_lon=9.32),
            "081110000000",
        )

    async def fake_features(layer, **kwargs):
        assert kwargs["bbox"] is None
        assert kwargs["cql_filter"] == (
            "official_region_code = '081110000000'"
        )
        return {"features": []}

    monkeypatch.setattr(health.geocode, "resolve_region", fake_region)
    monkeypatch.setattr(health.wfs, "features", fake_features)

    result = await health.data_health("Stuttgart", "charging")

    assert result["items"][0]["area_used"] == {
        "method": "official_region_code",
        "official_region_code": "081110000000",
        "label": "Stuttgart",
    }



def test_health_reports_live_age_statistics_and_oldest_site() -> None:
    now = datetime.now(UTC)
    records = [
        {
            "name": "Five minutes old",
            "updated": (now - timedelta(minutes=5)).isoformat(),
        },
        {
            "name": "Fifteen minutes old",
            "updated": (now - timedelta(minutes=15)).isoformat(),
        },
        {
            "name": "One hour old",
            "updated": (now - timedelta(minutes=60)).isoformat(),
        },
        {"name": "No realtime source"},
    ]

    result = health._classify_records(records, "updated")

    assert result["groups"] == {
        "live_and_fresh": 2,
        "live_capable_but_stale": 1,
        "no_live_feed": 1,
    }
    assert result["freshness_threshold_minutes"] == 30
    assert result["median_age_min"] == pytest.approx(15.0, abs=0.1)
    assert result["max_age_min"] == pytest.approx(60.0, abs=0.1)
    assert result["oldest_site"]["name"] == "One hour old"
    assert result["oldest_site"]["last_updated_at"] == records[2]["updated"]


@pytest.mark.asyncio
async def test_health_splits_fresh_stale_and_static_parking(monkeypatch) -> None:
    async def fake_region(region):
        return (
            Location(lat=49.14, lon=9.21, label="Heilbronn"),
            BBox(min_lat=49.1, min_lon=9.1, max_lat=49.2, max_lon=9.3),
            "081210000000",
        )

    async def fake_parking(params):
        assert params == {"official_region_code": "081210000000"}
        return [
            {
                "name": "Fresh garage",
                "type": "UNDERGROUND",
                "realtime_data_updated_at": "2099-01-01T00:00:00Z",
            },
            {
                "name": "Stale car park",
                "type": "CAR_PARK",
                "has_realtime_data": False,
                "realtime_data_updated_at": "2020-01-01T00:00:00Z",
            },
            {"name": "Static car park", "type": "CAR_PARK"},
            {"name": "Street spaces", "type": "ON_STREET"},
        ]

    monkeypatch.setattr(health.geocode, "resolve_region", fake_region)
    monkeypatch.setattr(health.parkapi, "all_parking_sites", fake_parking)

    result = await health.data_health("Heilbronn", "parking")
    item = result["items"][0]

    assert item["count"] == 3
    assert item["groups"] == {
        "live_and_fresh": 1,
        "live_capable_but_stale": 1,
        "no_live_feed": 1,
    }
    assert item["live_percent"] == 50.0
    assert item["live_percent_basis"] == (
        "live_and_fresh / (live_and_fresh + live_capable_but_stale)"
    )
    assert item["freshness_threshold_minutes"] == 30
    assert item["stale_sites"][0]["name"] == "Stale car park"
    assert item["stale_sites"][0]["last_updated_at"] == "2020-01-01T00:00:00Z"
    assert item["area_used"] == {
        "method": "official_region_code",
        "official_region_code": "081210000000",
        "label": "Heilbronn",
    }
    assert item["parking_type_counts_before_scope_filter"] == {
        "off_street": 3,
        "on_street": 1,
    }

    on_street = await health.data_health(
        "Heilbronn", "parking", parking_scope="on_street"
    )
    assert on_street["items"][0]["count"] == 1
    assert on_street["items"][0]["groups"]["no_live_feed"] == 1

