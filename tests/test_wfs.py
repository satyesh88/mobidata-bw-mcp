from typing import Any

import pytest

from mobidata_bw_mcp.clients import wfs
from mobidata_bw_mcp.clients.wfs import validate_filter
from mobidata_bw_mcp.models import BBox


def test_simple_cql_filter_is_allowed() -> None:
    assert validate_filter("form_factor = 'bicycle' AND current_range_meters > 1000")


@pytest.mark.parametrize(
    "value",
    ["name = 'x'; DROP TABLE things", "name = 'x' -- comment", "name = 'x' || chr(10)"],
)
def test_unsafe_cql_filter_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_filter(value)


@pytest.mark.asyncio
async def test_wfs_requests_wgs84_so_projected_layers_return_lat_lon(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_layers() -> list[dict[str, str]]:
        return [{"name": "MobiData-BW:radvis_cycle_network"}]

    async def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        seen.update(params)
        return {"features": []}

    monkeypatch.setattr(wfs, "list_layers", fake_layers)
    monkeypatch.setattr(wfs.http, "get_json", fake_get_json)

    await wfs.features(
        "MobiData-BW:radvis_cycle_network",
        bbox=BBox(min_lat=48.5, min_lon=9.0, max_lat=48.6, max_lon=9.1),
    )

    assert seen["srsName"] == "EPSG:4326"
    assert seen["bbox"].endswith("EPSG:4326")
