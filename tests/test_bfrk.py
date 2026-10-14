from pathlib import Path

import pytest

from mobidata_bw_mcp.clients import bfrk
from mobidata_bw_mcp.tools.health import _accessibility_coverage

FIXTURES = Path(__file__).parent / "fixtures" / "bfrk"


def test_parse_csv_handles_bom_semicolon_and_decimal_comma() -> None:
    rows = bfrk.parse_csv("\ufeffID;Latitude\nstop-1;49,2025622\n")

    assert rows == [{"ID": "stop-1", "Latitude": "49,2025622"}]


@pytest.mark.asyncio
async def test_joined_stop_uses_stop_id_and_hst_dhid(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fixture_table(_mode: str, filename: str) -> list[dict[str, str]]:
        path = FIXTURES / filename
        return bfrk.parse_csv(path.read_text(encoding="utf-8")) if path.exists() else []

    monkeypatch.setattr(bfrk, "table", fixture_table)

    result = await bfrk.joined_stop("SPNV", "de:08126:11951")

    assert result["Haltestelle"]["ID"].startswith("ID: de:08126:11951")
    assert result["Haltestelle"]["HST_DHID"] == "de:08126:11951"
    assert result["Haltestelle"]["HST_Name"] == "Waldenburg Bahnhof"
    assert result["Rampe"][0]["Laengsneigung_prozent"] == "5,987"


def test_accessibility_coverage_distinguishes_zero_from_missing() -> None:
    result = _accessibility_coverage(
        [
            {"capacity_disabled": 0, "realtime_free_capacity_disabled": 0},
            {"capacity_disabled": 2},
            {},
        ]
    )

    assert result["with_disabled_capacity_count"] == 2
    assert result["with_disabled_capacity_percent"] == 66.7
    assert result["with_live_disabled_free_count"] == 1
    assert result["with_live_disabled_free_percent"] == 33.3