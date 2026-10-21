import pytest

from mobidata_bw_mcp.models import Location
from mobidata_bw_mcp.tools import sharing


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

