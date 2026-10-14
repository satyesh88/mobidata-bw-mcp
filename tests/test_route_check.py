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
    assert result["query"]["effective_buffer_m"] == 500
    assert result["query"]["route_source"] == "straight_line_waypoints"


@pytest.mark.asyncio
async def test_waypoint_route_reports_l1036_closure(monkeypatch) -> None:
    closure = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[9.3000, 49.1630], [9.3050, 49.1680]],
        },
        "properties": {
            "type": "ROAD_CLOSED",
            "subtype": "ROAD_CLOSED_CONSTRUCTION",
            "description": "L1036 Erneuerung der Fahrbahn",
            "street": "L1036 Weinsberg-Eberstadt",
            "starttime": "2026-10-12T00:00:00+02:00",
            "endtime": "2026-12-04T23:59:00+01:00",
        },
    }

    async def fake_roadworks(_area, active_date):
        from shapely.geometry import shape

        assert active_date == date(2026, 10, 15)
        return [(closure, shape(closure["geometry"]))]

    async def no_signs(*_args):
        return []

    async def no_routed_geometry(_route):
        return None

    monkeypatch.setattr(route_check, "selected_roadworks", fake_roadworks)
    monkeypatch.setattr(route_check, "selected_signs", no_signs)
    monkeypatch.setattr(route_check.routing, "driving_hgv_line", no_routed_geometry)

    result = await route_check.check_route(
        [
            {"lat": 49.1427, "lon": 9.2187},
            {"lat": 49.1513, "lon": 9.2855},
            {"lat": 49.1808, "lon": 9.3217},
        ],
        date_value=date(2026, 10, 15),
    )

    assert any("L1036" in item["street"] for item in result["items"])


@pytest.mark.asyncio
async def test_approximated_route_separates_near_roadworks(monkeypatch) -> None:
    nearby = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[9.204, 49.141], [9.206, 49.141]],
        },
        "properties": {
            "type": "CONSTRUCTION",
            "description": "Parallel street works",
        },
    }

    async def fake_roadworks(*_args):
        from shapely.geometry import shape

        return [(nearby, shape(nearby["geometry"]))]

    async def empty(*_args):
        return []

    async def no_routed_geometry(_route):
        return None

    monkeypatch.setattr(route_check, "selected_roadworks", fake_roadworks)
    monkeypatch.setattr(route_check, "selected_signs", empty)
    monkeypatch.setattr(route_check.routing, "driving_hgv_line", no_routed_geometry)

    result = await route_check.check_route(
        [{"lat": 49.14, "lon": 9.20}, {"lat": 49.14, "lon": 9.21}]
    )

    assert result["items"][0]["route_relation"] == "near_route"
    assert result["items"][0]["distance_to_route_m"] > 30
    assert "0 findings on the route and 1 near the route" in result["warnings"][0]