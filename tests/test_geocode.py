import pytest

from mobidata_bw_mcp.clients import geocode


@pytest.mark.parametrize(
    ("query", "latitude", "longitude", "result_type"),
    [
        ("Weinsberger Kreuz", 49.1566648, 9.3057553, "motorway_junction"),
        ("Heilbronn Hbf", 49.1431403, 9.2076637, "station"),
        ("Heilbronn city centre", 49.1422910, 9.2186550, "city"),
        ("Stuttgart Hbf", 48.7856099, 9.1833959, "station"),
    ],
)
@pytest.mark.asyncio
async def test_verified_gazetteer_places(
    query: str, latitude: float, longitude: float, result_type: str
) -> None:
    result = await geocode.resolve(query)

    assert result.lat == pytest.approx(latitude)
    assert result.lon == pytest.approx(longitude)
    assert result.label
    assert result.type == result_type