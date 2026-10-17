from typing import Any

import pytest

from mobidata_bw_mcp.models import Location
from mobidata_bw_mcp.tools import accessibility


@pytest.mark.asyncio
async def test_find_accessible_parking_merges_filters_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(_location: Any) -> Location:
        return Location(lat=49.0, lon=9.0, label="Test location")

    async def fake_parking_sites(
        _params: dict[str, Any], _radius_m: int
    ) -> tuple[list[dict[str, Any]], int]:
        return (
            [
                {
                    "id": "live-accessible",
                    "name": "Live garage",
                    "lat": 49.002,
                    "lon": 9.0,
                    "capacity_disabled": 2,
                    "realtime_free_capacity_disabled": 1,
                    "realtime_data_updated_at": "2025-01-01T12:00:00Z",
                },
                {
                    "id": "not-accessible",
                    "lat": 49.001,
                    "lon": 9.0,
                    "capacity_disabled": 0,
                },
            ],
            1000,
        )

    async def fake_bfrk(_resolved: Location, _radius_m: int) -> list[dict[str, Any]]:
        return [
            {
                "id": "survey-accessible",
                "name": "Survey parking",
                "distance_m": 50,
                "capacity_disabled": 1,
                "source_label": "BFRK survey 2024",
            }
        ]

    monkeypatch.setattr(accessibility.geocode, "resolve", fake_resolve)
    monkeypatch.setattr(accessibility.parkapi, "nearest_parking_sites", fake_parking_sites)
    monkeypatch.setattr(accessibility, "_bfrk_parking", fake_bfrk)

    result = await accessibility.find_accessible_parking("Test", radius_m=1000)

    assert [item["id"] for item in result["items"]] == [
        "survey-accessible",
        "live-accessible",
    ]
    assert result["items"][1]["realtime_free_capacity_disabled"] == 1
    assert result["items"][1]["source_label"] == "live"
    assert len(result["warnings"]) >= 3
    assert "Datenlizenz Deutschland" in result["source"]["licence"]


@pytest.mark.asyncio
async def test_stop_accessibility_returns_measured_summary_and_caveats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = {
        "ID": "descriptive-id",
        "HST_DHID": "de:test:1",
        "HST_Name": "Test Bahnhof",
        "Gemeinde": "Teststadt",
        "Latitude": "49,0",
        "Longitude": "9,0",
        "Erfassungsdatum": "01.06.2024",
    }
    joined = {
        "Haltestelle": stop,
        "Haltesteig": [
            {
                "ID": "platform-1",
                "STEIG_Name": "Gleis 1",
                "Steighoehe_cm": "55,0",
                "Bodind_Leitstreifen": "ja",
                "Erfassungsdatum": "01.06.2024",
            }
        ],
        "Aufzug": [
            {
                "ID": "lift-1",
                "Tuerweite_cm": "100",
                "Kabinenbreite_cm": "110",
                "Kabinenlaenge_cm": "210",
                "DB-FaSta-ID": "1234",
                "Verbindungsfunktion": "Unterführung zu Gleis 1",
            }
        ],
        "Rampe": [],
        "Toilette": [
            {
                "rollstuhltauglichAlle": "nein",
                "rollstuhltauglich": "nein",
                "SchluesselEurokey": "ja",
            }
        ],
        "Treppe": [],
        "Engstelle": [],
        "Parkplatz": [{"Stellplatzanzahl_Behinderte": "2"}],
    }

    async def fake_select(_value: Any) -> tuple[str, dict[str, str], None]:
        return "SPNV", stop, None

    async def fake_joined(_mode: str, stop_id: str) -> dict[str, Any]:
        assert stop_id == "de:test:1"
        return joined

    monkeypatch.setattr(accessibility, "_select_stop", fake_select)
    monkeypatch.setattr(accessibility.bfrk, "joined_stop", fake_joined)

    result = await accessibility.stop_accessibility("Test Bahnhof")
    item = result["items"][0]

    assert item["step_free"] == "yes"
    assert item["platform_access"] == [
        {
            "platform": "Gleis 1",
            "platform_id": "platform-1",
            "step_free": "yes",
        }
    ]
    assert item["step_free_basis"] == (
        "Every surveyed platform has matching elevator or ramp access."
    )
    assert item["platform_or_curb_heights_cm"] == [55.0]
    assert item["elevators"][0]["db_fasta_id"] == "1234"
    assert item["disabled_parking_spaces"] == 2
    assert item["wheelchair_toilets"][0] == {
        "description": "accessible toilet (Euroschlüssel needed)",
        "wheelchair_accessible": "yes",
        "euro_key_needed": True,
        "source_fields": {
            "rollstuhltauglich": "nein",
            "rollstuhltauglichAlle": "nein",
            "SchluesselEurokey": "ja",
        },
    }
    assert any("not live operational status" in warning for warning in result["warnings"])


def test_step_free_is_no_only_for_platform_with_stairs_and_no_accessible_path() -> None:
    joined = {
        "Haltesteig": [
            {"ID": "platform-1", "STEIG_Name": "Gleis 1"},
            {"ID": "platform-2", "STEIG_Name": "Gleis 2"},
        ],
        "Aufzug": [{"Verbindungsfunktion": "Unterführung zu Gleis 1"}],
        "Rampe": [{"Verbindungsfunktion": "Neigung eigentlich 29,2"}],
        "Treppe": [
            {"Verbindungsfunktion": "Nebenausgang"},
            {"Verbindungsfunktion": "Unterführung zu Gleis 2"},
        ],
    }

    platforms = accessibility._platform_access(joined)
    status, basis = accessibility._step_free_summary(platforms)

    assert [platform["step_free"] for platform in platforms] == ["yes", "no"]
    assert status == "no"
    assert basis == "At least one surveyed platform has only matching stair access."


def test_step_free_is_unknown_when_platform_path_evidence_is_missing() -> None:
    joined = {
        "Haltesteig": [{"ID": "platform-8", "STEIG_Name": "Gleis 8"}],
        "Aufzug": [],
        "Rampe": [],
        "Treppe": [{"Verbindungsfunktion": "Bahnhofsgebäude zum Vorplatz"}],
    }

    platforms = accessibility._platform_access(joined)
    status, basis = accessibility._step_free_summary(platforms)

    assert platforms[0]["step_free"] == "unknown"
    assert status == "unknown"
    assert basis == "Not every surveyed platform has conclusive access-path evidence."


@pytest.mark.asyncio
async def test_stop_selection_normalizes_hbf_and_prefers_spnv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stops = [
        (
            "OEPNV",
            {
                "HST_DHID": "bus:1",
                "HST_Name": "Hauptbahnhof Bussteig",
                "Gemeinde": "Heilbronn",
                "Latitude": "49,1",
                "Longitude": "9,2",
            },
        ),
        (
            "SPNV",
            {
                "HST_DHID": "rail:1",
                "HST_Name": "Hauptbahnhof / Willy-Brandt-Platz",
                "Gemeinde": "Heilbronn",
                "Latitude": "49,1",
                "Longitude": "9,2",
            },
        ),
    ]

    async def fake_stops() -> list[tuple[str, dict[str, str]]]:
        return stops

    monkeypatch.setattr(accessibility, "_all_stops", fake_stops)

    mode, stop, distance = await accessibility._select_stop("Heilbronn Hbf")

    assert mode == "SPNV"
    assert stop["HST_DHID"] == "rail:1"
    assert distance is None