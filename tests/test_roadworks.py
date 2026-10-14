from datetime import date

import pytest

from mobidata_bw_mcp.tools import roadworks


@pytest.mark.asyncio
async def test_roadworks_active_during_any_day_in_range(monkeypatch) -> None:
    payload = {
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.22, 49.14]},
                "properties": {
                    "id": "overlap",
                    "street": "B 27",
                    "starttime": "2026-10-10T00:00:00+02:00",
                    "endtime": "2026-10-15T23:59:00+02:00",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.22, 49.14]},
                "properties": {
                    "id": "later",
                    "starttime": "2026-10-25T00:00:00+02:00",
                    "endtime": "2026-10-26T23:59:00+01:00",
                },
            },
        ]
    }

    async def fake_roadworks() -> dict:
        return payload

    monkeypatch.setattr(roadworks.static_files, "roadworks", fake_roadworks)

    result = await roadworks.get_roadworks(
        bbox={"min_lat": 49.1, "min_lon": 9.1, "max_lat": 49.2, "max_lon": 9.3},
        active_from=date(2026, 10, 12),
        active_to=date(2026, 10, 18),
    )

    assert [item["id"] for item in result["items"]] == ["overlap"]
    assert result["query"]["active_from"] == "2026-10-12"
    assert result["query"]["active_to"] == "2026-10-18"