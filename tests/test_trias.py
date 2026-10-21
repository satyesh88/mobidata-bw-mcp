"""Synthetic source responses test TRIAS semantics without credentials or live traffic."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from xml.etree.ElementTree import Element

import httpx
import pytest
import respx
from defusedxml.ElementTree import fromstring

from mobidata_bw_mcp.clients import trias as api
from mobidata_bw_mcp.models import Location
from mobidata_bw_mcp.tools import trias

URL = "https://efa-bw.de/trias"
FIXTURES = Path(__file__).parent / "fixtures" / "trias"
RESOLVE_STATION = api.resolve_station
START = datetime(2026, 10, 22, 7, tzinfo=UTC)
END = datetime(2026, 10, 22, 7, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_trias(monkeypatch):
    monkeypatch.setenv("TRIAS_REQUESTOR_REF", "synthetic-test-requestor")
    monkeypatch.setenv("TRIAS_URL", URL)
    api._CACHE.clear()
    api._STOPS.clear()
    monkeypatch.setattr(
        api,
        "resolve_station",
        AsyncMock(
            side_effect=lambda name: api.StopRef(
                "de:08121:26" if "Heilbronn" in name else "de:08111:6115",
                name,
            )
        ),
    )
    monkeypatch.setattr(
        api,
        "nearby_stops",
        AsyncMock(
            return_value=[
                api.StopRef("de:08121:26", "Heilbronn Hbf"),
            ]
        ),
    )
    yield
    api._CACHE.clear()


def fixture(name):
    return (FIXTURES / name).read_bytes()


def response(payload):
    return httpx.Response(200, content=payload)


@respx.mock
async def test_live_departures_keep_prediction_delay_cancellation_and_platform_change():
    route = respx.post(URL).mock(return_value=response(fixture("departures.xml")))
    result = await trias.get_live_departures("Heilbronn Hbf", START, END)
    assert [item["route"] for item in result["items"]] == ["S 4", "RE 8"]
    scheduled, predicted = result["items"]
    assert scheduled["is_live"] is False and "estimated_time" not in scheduled
    assert scheduled["cancelled"] is True
    assert predicted["is_live"] is True and predicted["delay_minutes"] == 7
    assert predicted["platform"] == "3" and predicted["scheduled_platform"] == "2"
    assert predicted["platform_changed"] is True
    assert predicted["wheelchair_accessible"] == "unknown"
    assert result["data_timestamp"] == "2026-10-22T07:00:00Z"
    assert result["source"]["dataset"] == "EFA-BW TRIAS"
    xml = fromstring(route.calls[0].request.content)
    assert xml.find(".//t:IncludeRealtimeData", api.NS).text == "true"
    assert xml.find(".//t:TimeWindow", api.NS).text == "PT1800S"
    assert xml.find(".//t:LocationName/t:Text", api.NS).text.startswith("Heilbronn")
    assert xml.find(".//s:RequestorRef", api.NS).text == "synthetic-test-requestor"


@respx.mock
async def test_prediction_time_controls_window_filter():
    respx.post(URL).mock(return_value=response(fixture("departures.xml")))
    result = await trias.get_live_departures(
        "de:08121:26",
        datetime(2026, 10, 22, 7, 10, tzinfo=UTC),
        END,
    )
    assert [item["route"] for item in result["items"]] == ["RE 8"]


@respx.mock
async def test_cache_hit_reuses_source_response_and_does_not_mutate_other_results():
    route = respx.post(URL).mock(return_value=response(fixture("departures.xml")))
    first = await trias.get_live_departures("de:08121:26", START, END)
    first["items"][0]["route"] = "mutated"
    second = await trias.get_live_departures("de:08121:26", START, END)
    assert route.call_count == 1
    assert second["items"][0]["route"] == "S 4"


@respx.mock
async def test_cache_is_separated_by_credential(monkeypatch):
    route = respx.post(URL).mock(return_value=response(fixture("departures.xml")))
    await api.request(Element("StopEventRequest"))
    monkeypatch.setenv("TRIAS_REQUESTOR_REF", "another-synthetic-key")
    await api.request(Element("StopEventRequest"))
    assert route.call_count == 2


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (502, "source_unavailable"),
        (504, "source_timeout"),
        (302, "source_unavailable"),
    ],
)
@respx.mock
async def test_http_errors_are_structured_without_following_redirects(status, code):
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            status,
            headers={"Location": "https://other.example/trias"},
        )
    )
    result = await trias.get_live_departures(
        "de:08121:26",
        START,
        END,
        fallback_to_schedule=False,
    )
    assert result["error"] == code and result["partial"] is True
    assert "items" not in result
    assert route.call_count == 1


@respx.mock
async def test_timeout_is_not_an_empty_timetable():
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("secret diagnostic"))
    result = await trias.get_live_departures(
        "de:08121:26",
        START,
        END,
        fallback_to_schedule=False,
    )
    assert result["error"] == "source_timeout"
    assert "secret diagnostic" not in str(result)


async def test_gtfs_fallback_is_explicitly_scheduled_and_keeps_source(monkeypatch):
    monkeypatch.delenv("TRIAS_REQUESTOR_REF")
    fallback = AsyncMock(
        return_value={
            "query": {},
            "items": [{"route": "RE"}],
            "source": {"dataset": "GTFS"},
            "warnings": [],
            "count": 1,
        }
    )
    monkeypatch.setattr(trias.transit, "get_departures", fallback)
    result = await trias.get_live_departures("Heilbronn Hbf", START, END)
    assert result["source"]["dataset"] == "GTFS"
    assert "scheduled only" in result["warnings"][0]
    assert result["query"]["realtime_status"] == "not_configured"
    assert result["items"][0]["is_live"] is False


@respx.mock
async def test_valid_empty_response_does_not_trigger_gtfs_fallback(monkeypatch):
    empty = b'<Trias xmlns="http://www.vdv.de/trias"><ServiceDelivery><DeliveryPayload><StopEventResponse/></DeliveryPayload></ServiceDelivery></Trias>'
    respx.post(URL).mock(return_value=response(empty))
    fallback = AsyncMock()
    monkeypatch.setattr(trias.transit, "get_departures", fallback)
    result = await trias.get_live_departures("de:08121:26", START, END)
    assert result["count"] == 0 and "error" not in result
    fallback.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        b"not XML",
        (
            b'<Trias xmlns="http://www.vdv.de/trias"><ServiceDelivery><DeliveryPayload>'
            b"<StopEventResponse><ErrorMessage><Text>synthetic-test-requestor private detail</Text>"
            b"</ErrorMessage></StopEventResponse></DeliveryPayload></ServiceDelivery></Trias>"
        ),
        b'<Trias xmlns="http://www.vdv.de/trias" xmlns:s="http://www.siri.org.uk/siri"><ServiceDelivery><s:Status>false</s:Status></ServiceDelivery></Trias>',
        b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><Trias>&secret;</Trias>',
    ],
)
@respx.mock
async def test_invalid_and_xml_level_error_responses_are_not_success(body, caplog):
    respx.post(URL).mock(return_value=response(body))
    result = await trias.get_live_departures(
        "de:08121:26",
        START,
        END,
        fallback_to_schedule=False,
    )
    assert result.get("error")
    assert "synthetic-test-requestor" not in str(result) + caplog.text
    assert "private detail" not in str(result) + caplog.text


@respx.mock
async def test_arrive_by_journey_keeps_all_legs_and_requests_accessibility():
    route = respx.post(URL).mock(return_value=response(fixture("journeys.xml")))
    result = await trias.plan_transit_journey(
        "Stuttgart Hbf",
        "Heilbronn Hbf",
        arrival_time=END,
        wheelchair=True,
        max_transfers=1,
    )
    item = result["items"][0]
    assert [leg["kind"] for leg in item["legs"]] == [
        "access_or_egress",
        "public_transport",
        "transfer",
    ]
    assert item["legs"][1]["board"]["delay_minutes"] == 2
    assert item["wheelchair_accessible"] == "unknown"
    assert any("not independently verified" in warning for warning in result["warnings"])
    xml = fromstring(route.calls[0].request.content)
    assert xml.find(".//t:Origin/t:DepArrTime", api.NS) is None
    assert xml.find(".//t:Destination/t:DepArrTime", api.NS).text == "2026-10-22T07:30:00Z"
    for tag in [
        "NoSingleStep",
        "NoStairs",
        "NoEscalator",
        "LevelEntrance",
        "IncludeEstimatedTimes",
    ]:
        assert xml.find(f".//t:{tag}", api.NS).text == "true"


async def test_unconfigured_journey_does_not_invent_a_route(monkeypatch):
    monkeypatch.delenv("TRIAS_REQUESTOR_REF")
    result = await trias.plan_transit_journey("Stuttgart Hbf", "Heilbronn Hbf")
    assert result["error"] == "not_configured" and "items" not in result


@pytest.mark.parametrize(
    "kwargs",
    [
        {"departure_time": START, "arrival_time": END},
        {"limit": 0},
        {"max_transfers": -1},
    ],
)
async def test_invalid_journey_options_make_no_request(kwargs, monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(api, "request", request)
    with pytest.raises(ValueError):
        await trias.plan_transit_journey("Stuttgart Hbf", "Heilbronn Hbf", **kwargs)
    request.assert_not_awaited()


def test_local_time_conversion_and_dst_ambiguity():
    assert trias._time(datetime(2026, 10, 22, 9)).hour == 7
    assert trias._time(datetime(2026, 12, 22, 9)).hour == 8
    with pytest.raises(ValueError, match="explicit UTC offset"):
        trias._time(datetime(2026, 10, 25, 2, 30))
    with pytest.raises(ValueError, match="explicit UTC offset"):
        trias._time(datetime(2026, 3, 29, 2, 30))


@respx.mock
async def test_coordinates_and_names_are_xml_escaped(monkeypatch):
    monkeypatch.setattr(
        trias.geocode,
        "resolve",
        AsyncMock(
            return_value=Location(
                lat=48.78,
                lon=9.18,
                label="Station & square <north>",
            )
        ),
    )
    route = respx.post(URL).mock(return_value=response(fixture("journeys.xml")))
    await trias.plan_transit_journey({"lat": 48.78, "lon": 9.18}, "de:08121:26", arrival_time=END)
    body = route.calls[0].request.content
    assert b"&amp;" in body and b"&lt;north&gt;" in body
    assert fromstring(body).find(".//t:Longitude", api.NS).text == "9.18"


@pytest.mark.parametrize("url", ["http://efa-bw.de/trias", "https://efa-bw.de/trias?key=secret"])
def test_insecure_or_credential_bearing_endpoint_is_rejected(monkeypatch, url):
    monkeypatch.setenv("TRIAS_URL", url)
    with pytest.raises(api.TriasError, match="invalid_endpoint"):
        api.configuration()


@respx.mock
async def test_trias_station_lookup_uses_provider_reference_and_24_hour_cache():
    xml = b"""<Trias xmlns="http://www.vdv.de/trias"><ServiceDelivery><DeliveryPayload>
      <LocationInformationResponse><LocationResult><Location><StopPoint>
      <StopPointRef>de:08121:26</StopPointRef><StopPointName><Text>Hauptbahnhof</Text></StopPointName>
      </StopPoint></Location></LocationResult></LocationInformationResponse>
      </DeliveryPayload></ServiceDelivery></Trias>"""
    route = respx.post(URL).mock(return_value=response(xml))
    first = await RESOLVE_STATION("Heilbronn Hbf")
    second = await RESOLVE_STATION("Heilbronn Hbf")
    assert first == second == api.StopRef("de:08121:26", "Hauptbahnhof")
    assert route.call_count == 1


@pytest.mark.parametrize("code", ["-4030", "-4000"])
@respx.mock
async def test_documented_no_result_codes_are_empty_searches_not_source_failures(code):
    xml = (
        f'<Trias xmlns="http://www.vdv.de/trias"><ServiceDelivery><DeliveryPayload>'
        f"<StopEventResponse><ErrorMessage><Code>{code}</Code></ErrorMessage>"
        "</StopEventResponse></DeliveryPayload></ServiceDelivery></Trias>"
    ).encode()
    respx.post(URL).mock(return_value=response(xml))
    result = await trias.get_live_departures("de:08121:26", START, END)
    assert result["count"] == 0
    assert "error" not in result
    assert result["source"]["dataset"] == "EFA-BW TRIAS"


@respx.mock
async def test_arrive_by_deadline_filters_later_source_results():
    respx.post(URL).mock(return_value=response(fixture("journeys.xml")))
    result = await trias.plan_transit_journey(
        "Stuttgart Hbf",
        "Heilbronn Hbf",
        arrival_time=datetime(2026, 10, 22, 6, 59, tzinfo=UTC),
    )
    assert result["count"] == 0


@respx.mock
async def test_depart_at_filters_source_journeys_before_requested_time():
    respx.post(URL).mock(return_value=response(fixture("journeys.xml")))
    result = await trias.plan_transit_journey(
        "Stuttgart Hbf",
        "Heilbronn Hbf",
        departure_time=START,
    )
    assert result["count"] == 0


@respx.mock
async def test_coordinate_access_is_explicit_and_bounded():
    route = respx.post(URL).mock(return_value=response(fixture("journeys.xml")))
    await trias.plan_transit_journey(
        {"lat": 48.78, "lon": 9.18},
        "Heilbronn Hbf",
        arrival_time=END,
    )
    xml = fromstring(route.calls[0].request.content)
    assert xml.find(".//t:IndividualTransportOptions/t:Mode", api.NS).text == "walk"
    assert xml.find(".//t:IndividualTransportOptions/t:MaxDuration", api.NS).text == "PT15M"


@respx.mock
async def test_siri_disruption_text_is_preserved_as_warning():
    xml = fixture("departures.xml").replace(
        b"<DeliveryPayload>",
        b'<DeliveryPayload><Situation xmlns="http://www.siri.org.uk/siri">'
        b"<Summary>Lift maintenance reported</Summary></Situation>",
    )
    respx.post(URL).mock(return_value=response(xml))
    result = await trias.get_live_departures("de:08121:26", START, END)
    assert "Lift maintenance reported" in result["warnings"]


@respx.mock
async def test_nearby_stop_groups_merge_and_keep_partial_data(monkeypatch):
    monkeypatch.setattr(
        api,
        "nearby_stops",
        AsyncMock(
            return_value=[
                api.StopRef("de:08121:26", "Main station"),
                api.StopRef("de:08121:1114", "Forecourt"),
            ]
        ),
    )
    route = respx.post(URL).mock(
        side_effect=[
            response(fixture("departures.xml")),
            httpx.Response(502),
        ]
    )
    result = await trias.get_live_departures({"lat": 49.14, "lon": 9.20}, START, END)
    assert route.call_count == 2
    assert result["count"] == 2
    assert any("partial" in warning for warning in result["warnings"])


@respx.mock
async def test_overlapping_nearby_stop_groups_do_not_duplicate_departures(monkeypatch):
    monkeypatch.setattr(
        api,
        "nearby_stops",
        AsyncMock(
            return_value=[
                api.StopRef("de:08121:26", "Main station"),
                api.StopRef("de:08121:1114", "Forecourt"),
            ]
        ),
    )
    respx.post(URL).mock(return_value=response(fixture("departures.xml")))
    result = await trias.get_live_departures({"lat": 49.14, "lon": 9.20}, START, END)
    assert result["count"] == 2
