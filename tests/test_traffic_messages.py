from datetime import date
from typing import Any

import pytest
from shapely.geometry import LineString

from mobidata_bw_mcp.clients import traffic_messages
from mobidata_bw_mcp.clients.http import SourceError
from mobidata_bw_mcp.models import Location
from mobidata_bw_mcp.tools import route_check
from mobidata_bw_mcp.tools import traffic_messages as traffic_tool

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<d2LogicalModel xmlns="http://datex2.eu/schema/2/2_0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" modelBaseVersion="2">
  <payloadPublication xsi:type="SituationPublication" lang="de-DE">
    <publicationTime>2026-10-17T18:17:35Z</publicationTime>
    <situation id="s1">
      <situationRecord id="r1" xsi:type="RoadOrCarriagewayOrLaneManagement">
        <validity>
          <validityTimeSpecification>
            <overallStartTime>2020-01-01T00:00:00Z</overallStartTime>
            <validPeriod><endOfPeriod>2099-11-08T22:59:00Z</endOfPeriod></validPeriod>
          </validityTimeSpecification>
        </validity>
        <generalPublicComment>
          <comment><values><value lang="de-DE">Hauptstraße
            gesperrt, Baustelle</value></values></comment>
          <commentType>description</commentType>
        </generalPublicComment>
        <generalPublicComment>
          <comment><values><value lang="de-DE">Zwischen A und B</value></values></comment>
          <commentType>locationDescriptor</commentType>
        </generalPublicComment>
        <groupOfLocations xsi:type="Linear">
          <locationForDisplay><latitude>49.1400</latitude><longitude>9.2050</longitude>
          </locationForDisplay>
          <tpegLinearLocation>
            <from xsi:type="TpegNonJunctionPoint"><pointCoordinates>
              <latitude>49.1395</latitude><longitude>9.2050</longitude>
            </pointCoordinates></from>
            <to xsi:type="TpegNonJunctionPoint"><pointCoordinates>
              <latitude>49.1405</latitude><longitude>9.2050</longitude>
            </pointCoordinates></to>
          </tpegLinearLocation>
        </groupOfLocations>
      </situationRecord>
    </situation>
    <situation id="s2">
      <situationRecord id="r2" xsi:type="Accident">
        <groupOfLocations xsi:type="Linear">
          <locationForDisplay><latitude>48.0</latitude><longitude>8.0</longitude>
          </locationForDisplay>
        </groupOfLocations>
      </situationRecord>
      <situationRecord id="r3" xsi:type="AbnormalTraffic" />
    </situation>
  </payloadPublication>
</d2LogicalModel>
"""


def test_parse_extracts_geometry_text_validity_and_skips_records_without_location() -> None:
    published, records = traffic_messages.parse(SAMPLE)

    assert published == "2026-10-17T18:17:35Z"
    assert [record["id"] for record in records] == ["r1", "r2"]
    closure = records[0]
    assert closure["category"] == "road_management"
    assert closure["description"] == "Hauptstraße gesperrt, Baustelle"
    assert closure["location_description"] == "Zwischen A und B"
    assert closure["start"] == "2020-01-01T00:00:00Z"
    assert closure["end"] == "2099-11-08T22:59:00Z"
    assert isinstance(closure["geometry"], LineString)
    assert records[1]["geometry"].geom_type == "Point"


def test_parse_rejects_entity_expansion() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'

    with pytest.raises(Exception):  # noqa: B017 - defusedxml raises EntitiesForbidden
        traffic_messages.parse(bomb)


def _patch_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def feed() -> Any:
        return traffic_messages.parse(SAMPLE)

    monkeypatch.setattr(traffic_messages, "messages", feed)


@pytest.mark.asyncio
async def test_find_traffic_messages_filters_by_radius_and_flags_closures(monkeypatch) -> None:
    _patch_feed(monkeypatch)

    async def fake_resolve(_location: Any) -> Location:
        return Location(lat=49.1400, lon=9.2040)

    monkeypatch.setattr(traffic_tool.geocode, "resolve", fake_resolve)

    result = await traffic_tool.find_traffic_messages("Test", radius_m=2000)

    assert [item["id"] for item in result["items"]] == ["r1"]
    assert result["items"][0]["severity"] == "high"
    assert result["items"][0]["distance_m"] < 100
    assert result["data_timestamp"].startswith("2026-10-17T18:17")
    assert result["source"]["dataset"] == "meldung"
    assert "Datenlizenz Deutschland" in result["source"]["licence"]


@pytest.mark.asyncio
async def test_records_with_same_text_and_place_are_reported_once(monkeypatch) -> None:
    from shapely.geometry import box

    _published, records = traffic_messages.parse(SAMPLE)
    duplicate = {**records[0], "id": "r1-copy", "category": "roadworks"}

    async def feed() -> Any:
        return None, [records[0], duplicate]

    monkeypatch.setattr(traffic_messages, "messages", feed)

    _published, selected = await traffic_tool.selected_traffic_messages(
        box(9.0, 49.0, 9.4, 49.3), date(2026, 10, 20)
    )

    assert [record["id"] for record in selected] == ["r1"]


@pytest.mark.asyncio
async def test_check_route_reports_traffic_messages(monkeypatch) -> None:
    _patch_feed(monkeypatch)

    async def empty(*_args: Any) -> list:
        return []

    monkeypatch.setattr(route_check, "selected_roadworks", empty)
    monkeypatch.setattr(route_check, "selected_signs", empty)
    route = {"type": "LineString", "coordinates": [[9.2000, 49.1400], [9.2100, 49.1400]]}

    result = await route_check.check_route(route, date_value=date(2026, 10, 20))

    assert result["count"] == 1
    assert result["items"][0]["kind"] == "traffic_message"
    assert result["items"][0]["severity"] == "high"
    assert "1 traffic messages" in result["warnings"][0]


@pytest.mark.asyncio
async def test_check_route_survives_traffic_feed_failure(monkeypatch) -> None:
    async def broken() -> Any:
        raise SourceError("down")

    async def empty(*_args: Any) -> list:
        return []

    monkeypatch.setattr(traffic_messages, "messages", broken)
    monkeypatch.setattr(route_check, "selected_roadworks", empty)
    monkeypatch.setattr(route_check, "selected_signs", empty)
    route = {"type": "LineString", "coordinates": [[9.2000, 49.1400], [9.2100, 49.1400]]}

    result = await route_check.check_route(route, date_value=date(2026, 10, 20))

    assert result["count"] == 0
    assert any("Traffic messages were unavailable" in w for w in result["warnings"])
