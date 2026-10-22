import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from defusedxml.ElementTree import fromstring

pytest.importorskip("anthropic")
pytest.importorskip("telegram")

from anthropic.types import TextBlock, ToolUseBlock

from mobidata_bw_mcp import transit_format
from mobidata_bw_mcp.telegram_bot import agent as agent_module
from mobidata_bw_mcp.telegram_bot.agent import AgentAnswer, MobilityAgent, _morning_date
from mobidata_bw_mcp.telegram_bot.main import BotHandlers, Settings
from mobidata_bw_mcp.telegram_bot.mcp_bridge import MCPBridge
from mobidata_bw_mcp.telegram_bot.timefmt import localize_tool_result
from mobidata_bw_mcp.tools import trias
from mobidata_bw_mcp.transit_format import (
    render_departures,
    render_journeys,
    time_label,
)

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture(autouse=True)
def fixed_transit_clock(monkeypatch):
    now = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(trias, "_now", lambda: now)
    monkeypatch.setattr(transit_format, "_now", lambda: now)


def departure(index=0, **extra):
    stamp = datetime(2026, 10, 22, 0, 10, tzinfo=UTC) + timedelta(minutes=index)
    return {
        "scheduled_time": stamp.isoformat(),
        "is_live": True,
        "route": f"N{index}",
        "headsign": "Schlossplatz",
        "stop_id": "test-stop",
        **extra,
    }


def test_delayed_stop_event_renders_scheduled_then_estimated_once():
    call = fromstring("""<CallAtStop xmlns="http://www.vdv.de/trias"><ServiceDeparture>
        <TimetabledTime>2026-10-22T00:10:00Z</TimetabledTime>
        <EstimatedTime>2026-10-22T00:12:00Z</EstimatedTime>
        </ServiceDeparture></CallAtStop>""")
    item = trias._call(call)
    assert item["scheduled_time"] == "2026-10-22T00:10:00Z"
    assert item["estimated_time"] == "2026-10-22T00:12:00Z"
    assert item["delay_minutes"] == 2
    assert time_label(item) == "scheduled 02:10 — est. 02:12 (+2 min)"
    localized = json.loads(localize_tool_result(json.dumps(item)))
    assert time_label(localized) == time_label(item)


@pytest.mark.parametrize(
    "prediction,status",
    [
        (None, "no live prediction"),
        ("2026-10-22T00:10:00Z", "on time"),
        ("2026-10-22T00:08:00Z", "est. 02:08 (-2 min)"),
    ],
)
def test_departure_prediction_status(prediction, status):
    item = departure(estimated_time=prediction)
    assert time_label(item) == "scheduled 02:10 — " + status


def test_winter_departure_uses_its_own_date_offset():
    assert time_label(
        {
            "scheduled_time": "2026-12-22T01:10:00Z",
            "estimated_time": "2026-12-22T01:12:00Z",
            "is_live": True,
        },
        now=datetime(2026, 12, 22, 1, tzinfo=UTC),
    ) == ("scheduled 02:10 — est. 02:12 (+2 min)")


def test_phone_pages_have_eight_departures_and_no_internal_limit_text():
    data = {
        "items": [departure(i) for i in range(20)],
        "next_cursor": 30,
        "warnings": ["Result cap reached"],
        "window_complete": False,
    }
    first, end = render_departures(data)
    assert end == 8
    assert first.count("scheduled ") == 8
    assert first.endswith("8 departures shown. More?")
    assert "cap" not in first
    second, end = render_departures(data, end)
    assert second.count("scheduled ") == 8
    assert "N8" in second and "N0 ·" not in second
    assert end == 16


@pytest.mark.parametrize(
    "question",
    [
        "Tomorrow morning departures",
        "Abfahrten morgen früh",
        "Departures tomorrow",
        "Abfahrten morgen",
    ],
)
def test_morning_after_midnight_resolves_to_today(question):
    now = datetime(2026, 10, 22, 1, 39, tzinfo=BERLIN)
    assert _morning_date(question, now).isoformat() == "2026-10-22"
    assert "2026-10-22" in agent_module._system_prompt(now)


def test_morning_after_four_uses_next_calendar_date():
    now = datetime(2026, 10, 22, 4, 0, tzinfo=BERLIN)
    assert _morning_date("tomorrow morning departures", now).isoformat() == "2026-10-23"


def test_explicit_date_is_not_silently_overwritten():
    now = datetime(2026, 10, 22, 1, 39, tzinfo=BERLIN)
    assert _morning_date("tomorrow morning on 23 October", now) is None


def response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


async def test_agent_corrects_morning_tool_date_and_renders_phone_data(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setattr(
        agent_module,
        "_berlin_now",
        lambda: datetime(
            2026,
            10,
            22,
            1,
            39,
            tzinfo=BERLIN,
        ),
    )
    bridge = MCPBridge()
    bridge.tools = [{"name": "get_live_departures", "description": "", "input_schema": {}}]
    bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            isError=False,
            content=[],
            structuredContent={
                "items": [departure(i) for i in range(12)],
                "query": {"resolved_stop": {"name": "Stuttgart Hbf"}},
                "count": 12,
            },
        )
    )
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            response(
                ToolUseBlock(
                    type="tool_use",
                    id="t",
                    name="get_live_departures",
                    input={
                        "stop_or_location": "Stuttgart Hbf",
                        "time_from": "2026-10-23T07:30:00",
                        "time_to": "2026-10-23T08:30:00",
                        "limit": 30,
                    },
                ),
                stop_reason="tool_use",
            ),
            response(
                TextBlock(
                    type="text",
                    text=(
                        "Mostly on time; N2 is running late.\n"
                        + render_departures({"items": [departure(i) for i in range(12)]})[0]
                        + "\nDaten: MobiData BW® / NVBW und Datengeber"
                    ),
                )
            ),
        ]
    )
    answer = await agent.answer("Departures tomorrow morning at Stuttgart Hbf", [])
    arguments = bridge.call_tool.await_args.args[1]
    assert arguments["time_from"] == "2026-10-22T07:30:00+02:00"
    assert arguments["time_to"] == "2026-10-22T08:30:00+02:00"
    assert answer.text.startswith("Mostly on time; N2 is running late.")
    assert answer.text.count("Searched around") == 1
    assert "Thu 22 Oct 2026" in answer.text
    sent = agent.client.messages.create.await_args_list[1].kwargs["messages"]
    tool_content = next(
        m["content"] for m in sent if m["role"] == "user" and isinstance(m["content"], list)
    )
    assert "compact_list" in tool_content[0]["content"]
    assert answer.text.count("scheduled ") == 8
    assert "More?" in answer.text
    assert "cap" not in answer.text and "ended" not in answer.text
    assert len(answer.departure_data["items"]) == 12


def test_different_departure_arrival_platforms_are_not_a_change():
    data = {
        "items": [
            {
                "transfers": 0,
                "legs": [
                    {
                        "kind": "public_transport",
                        "route": "RE8",
                        "board": {**departure(), "platform": "4"},
                        "alight": {**departure(10), "platform": "7"},
                    }
                ],
            }
        ]
    }
    text = render_journeys(data)
    assert "departs platform 4, arrives platform 7" in text
    assert "direct" in text and "change" not in text
    data["items"][0]["transfers"] = 1
    assert "1 change" in render_journeys(data)


async def test_more_uses_saved_departures_then_fetches_cursor_without_model():
    handler = BotHandlers(Settings("token", "model", 10, 30, frozenset(), 6), MCPBridge())
    data = {
        "items": [departure(i) for i in range(10)],
        "next_cursor": 10,
        "query": {
            "time_from": "2026-10-22T00:00:00Z",
            "time_to": "2026-10-22T04:00:00Z",
        },
    }
    handler.agent = SimpleNamespace(
        answer=AsyncMock(
            return_value=AgentAnswer(
                render_departures(data)[0],
                1,
                1,
                ["get_live_departures"],
                "end_turn",
                1,
                [],
                departure_data=data,
                departure_request={
                    "tool": "get_live_departures",
                    "arguments": {
                        "stop_or_location": "Stuttgart Hbf",
                        "limit": 10,
                    },
                },
            )
        )
    )
    handler.bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            isError=False,
            structuredContent={"items": [departure(10)], "window_complete": True},
        )
    )
    bot = SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    context = SimpleNamespace(bot=bot)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=2),
        effective_message=SimpleNamespace(text="Departures at Stuttgart Hbf"),
    )
    await handler.question(update, context)
    update.effective_message.text = "More?"
    await handler.question(update, context)
    assert bot.send_message.await_args.args[1].count("scheduled ") == 2
    handler.bridge.call_tool.assert_not_awaited()
    await handler.question(update, context)
    args = handler.bridge.call_tool.await_args.args[1]
    assert args["cursor"] == 10
    assert args["time_from"] == data["query"]["time_from"]
    handler.agent.answer.assert_awaited_once()
    assert "N10" in bot.send_message.await_args.args[1]


@pytest.mark.parametrize(
    "seconds,status", [(59, "on time"), (-59, "on time"), (90, "+2 min"), (-90, "-2 min")]
)
def test_delays_use_whole_minutes(seconds, status):
    stamp = datetime(2026, 10, 22, 0, 10, tzinfo=UTC)
    item = departure(estimated_time=(stamp + timedelta(seconds=seconds)).isoformat())
    assert status in time_label(item)


def test_six_hour_estimate_is_scheduled_even_when_equal():
    item = departure(scheduled_time="2026-10-22T06:00:00Z", estimated_time="2026-10-22T06:00:00Z")
    assert time_label(item) == "scheduled 08:00 (no live data yet)"
    item["estimated_time"] = "2026-10-22T06:08:00Z"
    assert "est." not in time_label(item)
    item = departure(estimated_time="2026-10-22T00:18:00Z", is_live=False)
    assert time_label(item) == "scheduled 02:10 — no live prediction"


def test_compact_list_has_full_line_name_and_scheduled_order_without_repeated_stop():
    late = departure(
        0,
        route="MEX12",
        stop_name="Heilbronn Hbf",
        platform="4",
        estimated_time="2026-10-22T00:20:00Z",
    )
    earlier_prediction = departure(1, route="S4", stop_name="Heilbronn Hbf")
    text, _ = render_departures({"items": [earlier_prediction, late]})
    assert text.index("MEX12") < text.index("S4")
    assert "Heilbronn Hbf" not in text
    assert "MEX12 · Schlossplatz · platform 4 · scheduled" in text
    assert "Thu 22 Oct" in text


@pytest.mark.parametrize(
    "planned,estimated,expected,changed",
    [
        ("7", "4", "4", True),
        ("7", "7", "7", False),
        ("7", None, "7", False),
        (None, "4", "4", False),
    ],
)
def test_arrival_bay_prefers_estimate_and_requires_both_for_change(
    planned, estimated, expected, changed
):
    bays = f"<PlannedBay><Text>{planned}</Text></PlannedBay>" if planned else ""
    bays += f"<EstimatedBay><Text>{estimated}</Text></EstimatedBay>" if estimated else ""
    call = fromstring(
        f'<LegAlight xmlns="http://www.vdv.de/trias">{bays}'
        "<ServiceArrival><TimetabledTime>2026-10-22T00:30:00Z</TimetabledTime>"
        "</ServiceArrival></LegAlight>"
    )
    result = trias._call(call, arrival=True)
    assert result["platform"] == expected
    assert result["platform_changed"] is changed


def test_transit_summary_stays_first_with_search_location_and_date():
    text = agent_module._finish_text(
        "Mostly on time.\nscheduled 02:10 — on time\nDaten: MobiData BW® / NVBW und Datengeber",
        "Departures tomorrow",
        datetime(2026, 10, 22, 1, 39, tzinfo=BERLIN),
        None,
        ("Heilbronn Hbf", "station"),
        "Assuming Thu 22 Oct.",
    )
    assert text.startswith("Mostly on time.\n")
    assert text.count("Searched around") == 1
    assert "Thu 22 Oct" in text
    assert text.endswith("Daten: MobiData BW® / NVBW und Datengeber")
