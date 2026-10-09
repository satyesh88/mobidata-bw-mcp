import pytest
from shapely.geometry import LineString

from mobidata_bw_mcp.geo import bbox_around, haversine_m, route_buffer_m
from mobidata_bw_mcp.models import Location


def test_haversine_and_bbox_use_meter_scale() -> None:
    heilbronn = Location(lat=49.1427, lon=9.2069)
    north = Location(lat=49.1517, lon=9.2069)

    assert haversine_m(heilbronn.lat, heilbronn.lon, north.lat, north.lon) == pytest.approx(
        1000, rel=0.03
    )
    bbox = bbox_around(heilbronn, 1000)
    assert bbox.min_lat < heilbronn.lat < bbox.max_lat
    assert bbox.min_lon < heilbronn.lon < bbox.max_lon


def test_route_buffer_is_in_meters() -> None:
    line = LineString([(9.20, 49.14), (9.21, 49.14)])
    buffered, local = route_buffer_m(line, 30)

    assert local.length == pytest.approx(729, rel=0.05)
    assert buffered.contains(local)