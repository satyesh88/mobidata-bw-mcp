from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("anthropic")
pytest.importorskip("telegram")

from mobidata_bw_mcp.telegram_bot import agent as agent_module
from mobidata_bw_mcp.telegram_bot.agent import (
    OFF_TOPIC_EN,
    OFF_TOPIC_MARKER,
    AgentAnswer,
    MobilityAgent,
    RecommendedPlace,
    _passed_date_line,
    _places_for_answer,
    _recommended_places,
    is_generic_name,
    place_label,
)
from mobidata_bw_mcp.telegram_bot.main import (
    BotHandlers,
    Settings,
    example_keyboard,
    navigation_keyboard,
)
from mobidata_bw_mcp.telegram_bot.mcp_bridge import MCPBridge
from mobidata_bw_mcp.telegram_bot.texts import EXAMPLES
from mobidata_bw_mcp.telegram_bot.timefmt import (
    localize_clock_text,
    localize_tool_result,
)

BERLIN = ZoneInfo("Europe/Berlin")


class Block:
    def __init__(self, block_type: str, **values: object) -> None:
        self.type = block_type
        self.__dict__.update(values)

    def model_dump(self, **_kwargs: object) -> dict[str, object]:
        return {"type": self.type, **{k: v for k, v in self.__dict__.items() if k != "type"}}


def response(*blocks: Block, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
    )


def tool_agent(items: list[dict], final_text: str, monkeypatch, now: datetime):
    monkeypatch.setattr(agent_module, "_berlin_now", lambda: now)
    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            structuredContent={
                "query": {"location": {"label": "Heilbronn Hbf", "type": "station"}},
                "data_timestamp": "2026-10-17T21:25:00Z",
                "items": items,
            },
            isError=False,
            content=[],
        )
    )
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            response(
                Block("tool_use", id="1", name="find_parking", input={"location": "x"}),
                stop_reason="tool_use",
            ),
            response(Block("text", text=final_text)),
        ]
    )
    return agent, bridge


# 1. Dates without a year


def test_passed_date_names_the_assumption_in_english() -> None:
    now = datetime(2026, 10, 17, 9, 0, tzinfo=BERLIN)

    line = _passed_date_line("Roadworks around Heilbronn on 15 Oct", now)

    assert line == "15 Oct has passed. Showing today's situation. Did you mean 15 Oct 2027?"


def test_passed_date_line_is_german_for_german_questions() -> None:
    now = datetime(2026, 10, 17, 9, 0, tzinfo=BERLIN)

    line = _passed_date_line("Baustelle am 15 Oktober ist hier", now)

    assert line == (
        "Der 15. Oktober ist vorbei. Ich zeige die heutige Lage. "
        "Meinten Sie den 15. Oktober 2027?"
    )


@pytest.mark.parametrize(
    "question",
    ["Roadworks on 17 Oct", "Roadworks on 20 Oct", "Roadworks on 15 Oct 2026", "Roadworks today"],
)
def test_today_future_and_explicit_year_dates_get_no_passed_line(question: str) -> None:
    now = datetime(2026, 10, 17, 9, 0, tzinfo=BERLIN)

    assert _passed_date_line(question, now) is None


def test_month_first_dates_are_recognised_but_times_are_not() -> None:
    now = datetime(2026, 10, 17, 9, 0, tzinfo=BERLIN)

    assert _passed_date_line("closures on Oct 3rd", now) is not None
    assert _passed_date_line("departures at oct 12:30", now) is None


@pytest.mark.asyncio
async def test_passed_date_is_the_first_line_and_the_prompt_forbids_next_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 17, 9, 0, tzinfo=BERLIN)
    agent, _bridge = tool_agent(
        [{"name": "Garage A", "lat": 49.1, "lon": 9.1}],
        "Garage A has free spaces.",
        monkeypatch,
        now,
    )

    answer = await agent.answer("Parking near Heilbronn Hbf on 15 Oct", [])

    lines = answer.text.splitlines()
    assert lines[0] == "15 Oct has passed. Showing today's situation. Did you mean 15 Oct 2027?"
    assert lines[1].startswith("📍 Searched around:")
    first_call = agent.client.messages.create.await_args_list[0].kwargs
    assert "has already passed this year" in str(first_call["messages"])
    assert "Do not use next year" in str(first_call["messages"])
    assert "2026-10-17" in str(first_call["messages"])
    assert "has already passed" in first_call["system"]


# 2. Berlin time everywhere


def test_tool_results_get_berlin_time_for_every_tool_shape() -> None:
    result = {
        "data_timestamp": "2026-10-17T21:25:00Z",
        "items": [
            {"last_updated": "2026-07-01T10:00:00+00:00", "name": "Summer"},
            {"nested": {"seen": ["2026-10-17 21:25:00+00:00"]}, "naive": "2026-10-17T21:25:00"},
        ],
        "note": "Stand 21:25",
    }

    import json

    converted = json.loads(localize_tool_result(json.dumps(result)))

    assert converted["data_timestamp"] == "2026-10-17T23:25:00+02:00"
    assert converted["items"][0]["last_updated"] == "2026-07-01T12:00:00+02:00"
    assert converted["items"][1]["nested"]["seen"] == ["2026-10-17T23:25:00+02:00"]
    assert converted["items"][1]["naive"] == "2026-10-17T21:25:00"
    assert converted["note"] == "Stand 21:25"


def test_winter_time_offset_is_plus_one() -> None:
    converted = localize_tool_result('{"t": "2026-12-01T10:00:00Z"}')

    assert converted == '{"t": "2026-12-01T11:00:00+01:00"}'


def test_non_json_results_are_unchanged() -> None:
    assert localize_tool_result("plain text 21:25 UTC") == "plain text 21:25 UTC"


def test_utc_clock_text_in_replies_is_converted() -> None:
    now = datetime(2026, 10, 17, 21, 30, tzinfo=UTC)

    text = localize_clock_text("Stand 21:25 UTC, Daten von 8:05 Uhr UTC; 12:00 bleibt.", now)

    assert text == "Stand 23:25, Daten von 10:05; 12:00 bleibt."


@pytest.mark.asyncio
async def test_model_sees_berlin_timestamps_and_reply_has_no_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 17, 23, 30, tzinfo=BERLIN)
    agent, _bridge = tool_agent(
        [{"name": "Garage A", "lat": 49.1, "lon": 9.1}],
        "Garage A: Stand 21:25 UTC.",
        monkeypatch,
        now,
    )

    answer = await agent.answer("Parking near Heilbronn Hbf", [])

    tool_result_call = agent.client.messages.create.await_args_list[1].kwargs
    assert "2026-10-17T23:25:00+02:00" in str(tool_result_call["messages"])
    assert "21:25:00Z" not in str(tool_result_call["messages"])
    assert "UTC" not in answer.text
    assert "Stand 23:25" in answer.text
    assert "Never write UTC" not in answer.text
    assert "never write UTC or Z" in tool_result_call["system"]


# 3. Navigation buttons and pin


def place(name: str, street: str | None, lat: float = 49.1) -> RecommendedPlace:
    return RecommendedPlace(name, lat, 9.1, "parking", street or "Heilbronn Hbf", street)


@pytest.mark.parametrize(
    "name",
    ["Parkplatz", "parkplatz 2", "Parkhaus", "Parking", "P+R", "Park & Ride", "Station", "Charger"],
)
def test_generic_names_are_detected(name: str) -> None:
    assert is_generic_name(name)


@pytest.mark.parametrize(
    "name", ["Parkhaus Hauptbahnhof", "Garage A", "Parkplatz Experimenta", "P1 Bahnhofstraße"]
)
def test_facility_names_are_not_generic(name: str) -> None:
    assert not is_generic_name(name)


def test_button_label_is_the_facility_name_or_the_street_for_generic_names() -> None:
    keyboard = navigation_keyboard(
        [
            place("Parkhaus Hauptbahnhof", "Am Hauptbahnhof 1"),
            place("Parkplatz", "Kaiserstraße 12", 49.2),
            place("Parkplatz", None, 49.3),
        ]
    )

    assert keyboard is not None
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "🧭 Parkhaus Hauptbahnhof",
        "🧭 Kaiserstraße 12",
        "🧭 Parkplatz",
    ]


def test_generic_street_label_comes_from_the_facility_address_not_the_search_anchor() -> None:
    result = (
        '{"query": {"location": {"label": "Heilbronn Hbf"}}, "items": '
        '[{"name": "Parkplatz", "address": {"street": "Kaiserstraße", "house_number": "12"}, '
        '"lat": 49.1, "lon": 9.1}, {"name": "Parkplatz", "lat": 49.2, "lon": 9.2}]}'
    )

    places = _recommended_places(result, "find_parking", {})

    assert place_label(places[0]) == "Kaiserstraße 12"
    assert place_label(places[1]) == "Parkplatz"
    assert places[1].street is None


def test_buttons_follow_the_order_the_text_mentions_places() -> None:
    nearest_first = [
        place("Garage Nord", "Nordstraße 1", 49.1),
        place("Parkhaus Mitte", "Mittelstraße 2", 49.2),
        place("Parkplatz", "Südstraße 3", 49.3),
    ]
    text = "Best: Parkhaus Mitte. Also Südstraße 3 and Garage Nord."

    ordered = _places_for_answer(text, nearest_first)

    assert [p.name for p in ordered] == ["Parkhaus Mitte", "Parkplatz", "Garage Nord"]
    keyboard = navigation_keyboard(ordered)
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "🧭 Parkhaus Mitte",
        "🧭 Südstraße 3",
        "🧭 Garage Nord",
    ]


def test_places_fall_back_to_tool_order_when_the_text_names_none() -> None:
    places = [place("Garage Nord", "Nordstraße 1"), place("Parkhaus Mitte", "Mittelstraße 2", 49.2)]

    assert _places_for_answer("Two options were found.", places) == places


@pytest.mark.asyncio
async def test_pin_is_the_top_recommendation_not_the_nearest() -> None:
    settings = Settings("123:token", "model", 10, 10, frozenset(), 10)
    handlers = BotHandlers(settings, MCPBridge())
    nearest = place("Garage Nord", "Nordstraße 1", 48.1)
    recommended = place("Parkplatz", "Südstraße 3", 48.2)
    text = "Best: Südstraße 3. Nearest: Garage Nord."
    ordered = _places_for_answer(text, [nearest, recommended])
    handlers.agent = SimpleNamespace(
        answer=AsyncMock(
            return_value=AgentAnswer(text, 1, 1, ["find_parking"], "end_turn", 1, ordered)
        )
    )
    bot = SimpleNamespace(
        send_chat_action=AsyncMock(), send_message=AsyncMock(), send_venue=AsyncMock()
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7), effective_chat=SimpleNamespace(id=8)
    )

    await handlers._answer(update, SimpleNamespace(bot=bot), "Parking near Heilbronn Hbf")

    bot.send_venue.assert_awaited_once_with(
        8, latitude=48.2, longitude=9.1, title="Südstraße 3", address="Südstraße 3"
    )
    buttons = bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
    assert [row[0].text for row in buttons] == ["🧭 Südstraße 3", "🧭 Garage Nord"]


# 4. Off-topic examples


@pytest.mark.asyncio
async def test_off_topic_marker_becomes_a_clean_decline_without_tools() -> None:
    bridge = MCPBridge()
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[response(Block("text", text=OFF_TOPIC_MARKER))]
    )

    answer = await agent.answer("Who won the football world cup?", [])

    assert answer.text == OFF_TOPIC_EN
    assert answer.off_topic
    assert answer.places == []


@pytest.mark.asyncio
async def test_off_topic_reply_gets_example_buttons_and_no_pin() -> None:
    settings = Settings("123:token", "model", 10, 10, frozenset(), 10)
    handlers = BotHandlers(settings, MCPBridge())
    handlers.agent = SimpleNamespace(
        answer=AsyncMock(
            return_value=AgentAnswer(OFF_TOPIC_EN, 1, 1, [], "end_turn", 0, [], off_topic=True)
        )
    )
    bot = SimpleNamespace(
        send_chat_action=AsyncMock(), send_message=AsyncMock(), send_venue=AsyncMock()
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7), effective_chat=SimpleNamespace(id=8)
    )

    await handlers._answer(update, SimpleNamespace(bot=bot), "Who won the world cup?")

    markup = bot.send_message.await_args.kwargs["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == list(EXAMPLES[:3])
    assert [row[0].callback_data for row in markup.inline_keyboard] == [
        "example:0",
        "example:1",
        "example:2",
    ]
    bot.send_venue.assert_not_awaited()


def test_example_keyboard_has_two_to_three_buttons() -> None:
    assert 2 <= len(example_keyboard().inline_keyboard) <= 3
