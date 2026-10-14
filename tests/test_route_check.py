from datetime import date

import pytest

from mobidata_bw_mcp.tools import route_check


@pytest.fixture
def route() -> dict:
    return {
        "type": "LineString",
        "coordinates": [[9.2000, 49.1400], [9.2100, 49.1400]],
    }


@pytest.mark.asyncio
async def test_check_route_filters_geometry_and_active_date(monkeypatch, route) -> None:
    crossing = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[9.2050, 49.1395], [9.2050, 49.1405]],
        },
        "properties": {
            "type": "ROAD_CLOSED",
            "subtype": "BOTH_DIRECTIONS",
            "description": "Bridge work",
            "street": "B 27",
            "starttime": "2026-10-01T00:00:00+02:00",
            "endtime": "2026-10-31T23:59:00+01:00",
        },
    }
    outside = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[9.2050, 49.1500], [9.2060, 49.1500]],
        },
        "properties": {"type": "CONSTRUCTION", "description": "Far away"},
    }

    async def fake_roadworks(area, active_date):
        assert active_date == date(2026, 10, 20)
        from shapely.geometry import shape

        return [(crossing, shape(crossing["geometry"])), (outside, shape(outside["geometry"]))]

    async def fake_signs(area, codes):
        return []

    monkeypatch.setattr(route_check, "selected_roadworks", fake_roadworks)
    monkeypatch.setattr(route_check, "selected_signs", fake_signs)

    result = await route_check.check_route(route, date_value=date(2026, 10, 20))

    assert result["count"] == 1
    assert result["items"][0]["description"] == "Bridge work"
    assert result["items"][0]["type"] == "ROAD_CLOSED"
    assert result["items"][0]["subtype"] == "BOTH_DIRECTIONS"
    assert result["items"][0]["severity"] == "high"
    assert result["items"][0]["km_from_start"] == pytest.approx(0.36, abs=0.05)


@pytest.mark.asyncio
async def test_check_route_warns_for_straight_line_points(monkeypatch) -> None:
    async def empty(*args):
        return []

    monkeypatch.setattr(route_check, "selected_roadworks", empty)
    monkeypatch.setattr(route_check, "selected_signs", empty)

    result = await route_check.check_route(
        [{"lat": 49.14, "lon": 9.20}, {"lat": 49.14, "lon": 9.21}]
    )

    assert "Straight lines" in result["warnings"][1]