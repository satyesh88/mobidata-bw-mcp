import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from mcp.types import Tool

pytest.importorskip("anthropic")
pytest.importorskip("telegram")

from mobidata_bw_mcp.telegram_bot.agent import AgentAnswer, RecommendedPlace
from mobidata_bw_mcp.telegram_bot.formatting import answer_html, safe_html
from mobidata_bw_mcp.telegram_bot.limits import DailyBudget, HourlyRateLimiter
from mobidata_bw_mcp.telegram_bot.main import (
    BotHandlers,
    EphemeralState,
    Settings,
    build_application,
    navigation_keyboard,
    navigation_url,
    travel_mode,
    uses_saved_location,
)
from mobidata_bw_mcp.telegram_bot.mcp_bridge import (
    MCPBridge,
    anthropic_tools,
    result_text,
    tool_error_result,
)
from mobidata_bw_mcp.telegram_bot.texts import ATTRIBUTION, EXAMPLES


class FakeBlock:
    def __init__(self, block_type: str, **values: object) -> None:
        self.type = block_type
        self.__dict__.update(values)

    def model_dump(self, **_kwargs: object) -> dict[str, object]:
        values = {key: value for key, value in self.__dict__.items() if key != "type"}
        return {"type": self.type, **values}


def fake_response(*blocks: FakeBlock, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
    )


def test_anthropic_tools_preserve_mcp_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    }
    converted = anthropic_tools(
        [Tool(name="find_parking", description="Find parking", inputSchema=schema)]
    )

    assert converted == [
        {
            "name": "find_parking",
            "description": "Find parking",
            "input_schema": schema,
        }
    ]


def test_navigation_buttons_are_ranked_capped_and_use_expected_modes() -> None:
    places = [
        RecommendedPlace("Garage", 49.1, 9.1, "parking", "Main St 1"),
        RecommendedPlace("Charger", 49.2, 9.2, "charger", "Main St 2"),
        RecommendedPlace("Scooter", 49.3, 9.3, "scooter", "Main St 3"),
        RecommendedPlace("Station", 49.4, 9.4, "station", "Main St 4"),
    ]

    keyboard = navigation_keyboard(places)

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 3
    assert travel_mode(places[0]) == "driving"
    assert travel_mode(places[2]) == "walking"
    assert keyboard.inline_keyboard[0][0].text == "🧭 Garage"
    assert keyboard.inline_keyboard[0][0].url == navigation_url(places[0])
    assert keyboard.inline_keyboard[2][0].url.endswith(
        "destination=49.3,9.3&travelmode=walking"
    )


def test_navigation_keyboard_is_absent_without_places() -> None:
    assert navigation_keyboard([]) is None


def test_tool_error_result_is_explicit_and_does_not_invent_a_cause() -> None:
    result = tool_error_result("stop_accessibility")

    assert result.isError
    assert result_text(result) == (
        '{"error": true, "message": "The accessibility lookup failed"}'
    )


def test_places_are_deduplicated_within_fifty_metres() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import _merge_places

    places = _merge_places(
        [],
        [
            RecommendedPlace("Platform 1", 49.14, 9.20, "station", "Station"),
            RecommendedPlace("Platform 2", 49.1401, 9.2001, "station", "Station"),
            RecommendedPlace("Other station", 49.15, 9.21, "station", "Other"),
        ],
    )

    assert [place.name for place in places] == ["Platform 1", "Other station"]


def test_model_result_count_matches_supplied_items() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import _model_result_text

    projected = __import__("json").loads(
        _model_result_text(
            '{"count": 5, "items": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]}'
        )
    )

    assert projected["count"] == len(projected["items"]) == 3
    assert projected["total_count"] == 5


@pytest.mark.asyncio
async def test_agent_returns_ranked_structured_places_from_tool_result() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Find parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            structuredContent={
                "query": {
                    "location": {
                        "label": "Stuttgart Hauptbahnhof",
                        "type": "station",
                    }
                },
                "items": [
                    {
                        "name": "Garage A",
                        "address": "Street 1",
                        "lat": 48.1,
                        "lon": 9.1,
                    },
                    {
                        "name": "Garage B",
                        "address": {"street": "Street", "house_number": "2"},
                        "lat": 48.2,
                        "lon": 9.2,
                    },
                ],
            },
            isError=False,
            content=[],
        )
    )
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock(
                    "tool_use",
                    id="1",
                    name="find_parking",
                    input={"location": "Stuttgart Hbf"},
                ),
                stop_reason="tool_use",
            ),
            fake_response(
                FakeBlock(
                    "text",
                    text="I recommend Garage A first; Garage B is another option.",
                )
            ),
        ]
    )

    answer = await agent.answer("Parking near Stuttgart Hbf", [])

    assert [place.name for place in answer.places] == ["Garage A", "Garage B"]
    assert answer.places[0].kind == "parking"
    assert answer.places[1].address == "Street 2"


@pytest.mark.asyncio
async def test_agent_injects_berlin_time_and_resolves_next_yearless_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mobidata_bw_mcp.telegram_bot import agent as agent_module

    fixed_now = datetime(2026, 10, 14, 23, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    monkeypatch.setattr(agent_module, "_berlin_now", lambda: fixed_now)
    bridge = MCPBridge()
    bridge.tools = [{"name": "check_route", "description": "Route", "input_schema": {}}]
    bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            structuredContent={
                "query": {"date": "2026-10-15"},
                "count": 1,
                "items": [{"street": "L1036", "kind": "roadwork"}],
            },
            isError=False,
            content=[],
        )
    )
    mobility_agent = agent_module.MobilityAgent(bridge, "model")
    mobility_agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock(
                    "tool_use",
                    id="route-1",
                    name="check_route",
                    input={
                        "route": ["Heilbronn", "Weinsberg", "Eberstadt"],
                        "date_value": "2026-10-15",
                    },
                ),
                stop_reason="tool_use",
            ),
            fake_response(FakeBlock("text", text="L1036 has a roadwork on the route.")),
        ]
    )

    answer = await mobility_agent.answer(
        "Check Heilbronn via Weinsberg to Eberstadt on 15 October", []
    )

    first_call = mobility_agent.client.messages.create.await_args_list[0].kwargs
    second_call = mobility_agent.client.messages.create.await_args_list[1].kwargs
    assert "2026-10-14T23:30:00+02:00" in first_call["system"]
    assert "next upcoming occurrence" in first_call["system"]
    assert "always call check_route" in first_call["system"]
    assert "pass all of them in travel" in first_call["system"]
    assert "order as route waypoints" in first_call["system"]
    assert "Never answer a route-between-places question using only get_roadworks" in (
        first_call["system"]
    )
    assert first_call["system"] == second_call["system"]
    assert "15 October = 2026-10-15" in str(first_call["messages"])
    bridge.call_tool.assert_awaited_once_with(
        "check_route",
        {
            "route": ["Heilbronn", "Weinsberg", "Eberstadt"],
            "date_value": "2026-10-15",
        },
    )
    assert "L1036" in answer.text
    assert answer.places == []


def test_only_eligible_tool_results_create_navigation_places() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import _recommended_places

    result = '{"items": [{"name": "Platform 1", "lat": 49.1, "lon": 9.1}]}'

    assert _recommended_places(result, "find_transit")[0].kind == "station"
    assert _recommended_places(result, "stop_accessibility")[0].kind == "station"
    assert _recommended_places(result, "check_route") == []
    assert _recommended_places(result, "get_roadworks") == []
    assert _recommended_places(result, "data_health") == []
    assert _recommended_places(result, "list_datasets") == []


def test_bike_parking_gets_bicycle_navigation() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import _recommended_places

    result = '{"items": [{"name": "Bike stands", "lat": 49.1, "lon": 9.1}]}'
    place = _recommended_places(result, "find_parking", {"purpose": "BIKE"})[0]

    assert place.kind == "bike_parking"
    assert "travelmode=bicycling" in navigation_url(place)


def test_unsolicited_correction_lines_are_removed() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import _without_unsolicited_corrections

    text = "Correction: my earlier parking answer was wrong.\nL1036 has a roadwork."

    assert _without_unsolicited_corrections(text, "What is on this route?") == (
        "L1036 has a roadwork."
    )
    assert _without_unsolicited_corrections(text, "Correct my earlier answer") == text


@pytest.mark.asyncio
async def test_agent_uses_neutral_accessibility_error_without_model_reason() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [
        {"name": "stop_accessibility", "description": "Accessibility", "input_schema": {}}
    ]
    bridge.call_tool = AsyncMock(return_value=tool_error_result("stop_accessibility"))
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock(
                    "tool_use",
                    id="1",
                    name="stop_accessibility",
                    input={"stop_or_location": "Heilbronn Hbf"},
                ),
                stop_reason="tool_use",
            ),
            fake_response(
                FakeBlock("text", text="The source is down because its CSV is malformed.")
            ),
        ]
    )

    answer = await agent.answer("Is Heilbronn Hbf accessible?", [])

    assert answer.text == "The accessibility lookup failed"
    assert answer.places == []
    model_messages = agent.client.messages.create.await_args_list[-1].kwargs["messages"]
    assert "\"error\": true" in str(model_messages)


@pytest.mark.asyncio
async def test_agent_converts_bridge_exception_to_explicit_error_result() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [
        {"name": "stop_accessibility", "description": "Accessibility", "input_schema": {}}
    ]
    bridge.call_tool = AsyncMock(side_effect=RuntimeError("private upstream detail"))
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock(
                    "tool_use",
                    id="1",
                    name="stop_accessibility",
                    input={"stop_or_location": "Heilbronn Hbf"},
                ),
                stop_reason="tool_use",
            ),
            fake_response(FakeBlock("text", text="I cannot explain the failure.")),
        ]
    )

    answer = await agent.answer("Is Heilbronn Hbf accessible?", [])

    assert answer.text == "The accessibility lookup failed"
    assert "private upstream detail" not in str(
        agent.client.messages.create.await_args_list[-1].kwargs["messages"]
    )


@pytest.mark.asyncio
async def test_agent_falls_back_to_first_tool_places_when_answer_names_none() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            structuredContent={
                "count": 1,
                "items": [{"name": "Garage", "lat": 49.1, "lon": 9.1}],
            },
            isError=False,
            content=[],
        )
    )
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock(
                    "tool_use",
                    id="1",
                    name="find_parking",
                    input={"location": "Heilbronn"},
                ),
                stop_reason="tool_use",
            ),
            fake_response(FakeBlock("text", text="I could not confirm a suitable place.")),
        ]
    )

    answer = await agent.answer("Find parking", [])

    assert [place.name for place in answer.places] == ["Garage"]


@pytest.mark.parametrize(
    ("question", "response_text"),
    [
        ("Parking near Heilbronn Hbf", "Two nearby parking options were found."),
        ("Parken am Heilbronn Hbf", "Zwei Parkmöglichkeiten wurden gefunden."),
    ],
)
@pytest.mark.asyncio
async def test_parking_questions_produce_buttons_in_english_and_german(
    question: str, response_text: str
) -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(
        return_value=SimpleNamespace(
            structuredContent={
                "items": [
                    {"name": "Garage A", "lat": 49.14, "lon": 9.21},
                    {"name": "Garage B", "lat": 49.15, "lon": 9.22},
                ]
            },
            isError=False,
            content=[],
        )
    )
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock(
                    "tool_use",
                    id="parking-1",
                    name="find_parking",
                    input={"location": "Heilbronn Hbf"},
                ),
                stop_reason="tool_use",
            ),
            fake_response(FakeBlock("text", text=response_text)),
        ]
    )

    answer = await agent.answer(question, [])
    keyboard = navigation_keyboard(answer.places)

    assert [place.name for place in answer.places] == ["Garage A", "Garage B"]
    assert keyboard is not None
    assert [row[0].text for row in keyboard.inline_keyboard] == [
        "🧭 Garage A",
        "🧭 Garage B",
    ]
    assert all("travelmode=driving" in row[0].url for row in keyboard.inline_keyboard)


@pytest.mark.asyncio
async def test_handler_sends_navigation_buttons_and_best_venue() -> None:
    settings = Settings("123:token", "model", 10, 10, frozenset(), 10)
    handlers = BotHandlers(settings, MCPBridge())
    places = [
        RecommendedPlace("Garage A", 48.1, 9.1, "parking", "Street 1"),
        RecommendedPlace("Garage B", 48.2, 9.2, "parking", "Street 2"),
    ]
    handlers.agent = SimpleNamespace(
        answer=AsyncMock(
            return_value=AgentAnswer(
                "Two nearby garages.", 10, 5, ["find_parking"], "end_turn", 1, places
            )
        )
    )
    bot = SimpleNamespace(
        send_chat_action=AsyncMock(),
        send_message=AsyncMock(),
        send_venue=AsyncMock(),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=8),
    )
    context = SimpleNamespace(bot=bot)

    await handlers._answer(update, context, "Parking near Stuttgart Hbf")

    reply_markup = bot.send_message.await_args.kwargs["reply_markup"]
    assert len(reply_markup.inline_keyboard) == 2
    bot.send_venue.assert_awaited_once_with(
        8,
        latitude=48.1,
        longitude=9.1,
        title="Garage A",
        address="Street 1",
    )


def test_safe_html_allows_only_supported_tags_and_links() -> None:
    rendered = safe_html(
        '<b>Safe</b><script>alert("x")</script>'
        '<a href="javascript:bad">bad</a><a href="https://example.com?a=1&b=2">ok</a>'
    )

    assert rendered == (
        '<b>Safe</b>alert(&quot;x&quot;)bad'
        '<a href="https://example.com?a=1&amp;b=2">ok</a>'
    )


def test_answer_html_caps_length_and_preserves_attribution() -> None:
    rendered = answer_html("first line\n" + "second line " * 200)

    assert len(rendered) <= 1200
    assert rendered.endswith(ATTRIBUTION)
    assert "… (reply &#x27;more&#x27; for the rest)" in rendered
    assert "second line" not in rendered


def test_safe_html_converts_markdown_bold() -> None:
    assert safe_html("**Live:** 12 spaces") == "<b>Live:</b> 12 spaces"


def test_answer_html_never_returns_attribution_only() -> None:
    rendered = answer_html(ATTRIBUTION)

    assert rendered.startswith("Sorry")
    assert rendered.endswith(ATTRIBUTION)


def test_tool_error_html_is_exactly_one_line() -> None:
    assert answer_html("The accessibility lookup failed") == (
        "The accessibility lookup failed"
    )


def test_hourly_rate_limiter_expires_old_messages() -> None:
    limiter = HourlyRateLimiter(2)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert limiter.allow(7, now)
    assert limiter.allow(7, now + timedelta(minutes=1))
    assert not limiter.allow(7, now + timedelta(minutes=2))
    assert limiter.allow(7, now + timedelta(hours=1, seconds=1))


def test_daily_budget_counts_usage_and_resets_next_day() -> None:
    budget = DailyBudget(0.00002)
    now = datetime.now(UTC)

    cost = budget.add_usage("claude-haiku-5-5", 10, 2, now)

    assert cost == pytest.approx(0.00002)
    assert not budget.available(now)
    assert budget.available(now + timedelta(days=1))
    assert budget.spent_usd == 0


def test_ephemeral_state_keeps_six_messages_and_expires() -> None:
    state = EphemeralState()
    for index in range(8):
        state.remember(1, "user", str(index))
    state.set_location(1, 49.14, 9.22)

    assert [message["content"] for message in state.history(1)] == ["2", "3", "4", "5", "6", "7"]
    assert state.location(1) == (49.14, 9.22)
    future = datetime.now(UTC) + timedelta(minutes=31)
    assert state.history(1, future) == []
    assert state.location(1, future) is None


@pytest.mark.parametrize(
    "question",
    ["What's near me?", "Was gibt es hier?", "Parken in der Nähe"],
)
def test_saved_location_phrases(question: str) -> None:
    assert uses_saved_location(question)


def test_named_place_does_not_use_saved_location() -> None:
    assert not uses_saved_location("Parking near Stuttgart Hbf")


@pytest.mark.asyncio
async def test_start_uses_four_example_buttons() -> None:
    class FakeMessage:
        def __init__(self) -> None:
            self.reply_markup = None

        async def reply_text(self, _text: str, **kwargs: object) -> None:
            self.reply_markup = kwargs["reply_markup"]

    settings = Settings("token", "model", 10, 10, frozenset(), 6)
    handlers = BotHandlers(settings, MCPBridge())
    message = FakeMessage()
    update = SimpleNamespace(effective_message=message)

    await handlers.start(update, None)

    assert len(message.reply_markup.inline_keyboard) == len(EXAMPLES) == 4


def test_application_builds_with_private_chat_filters() -> None:
    settings = Settings("123:token", "model", 10, 10, frozenset(), 6)

    application = build_application(settings)

    assert len(application.handlers[0]) == 7


def test_settings_reject_malformed_token_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "= 123:not-a-valid-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "configured")

    with pytest.raises(RuntimeError, match="invalid format") as error:
        Settings.from_environment()

    assert "not-a-valid-token" not in str(error.value)


def test_agent_adds_anthropic_workspace_header() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    agent = MobilityAgent(MCPBridge(), "model", workspace_id="wrk-test")

    assert agent.client.default_headers["anthropic-workspace-id"] == "wrk-test"


def test_searched_place_line_replaces_model_location_header() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import _with_searched_place

    rendered = _with_searched_place(
        "📍 Resolved: wrong label\n⚡ Two chargers",
        ("Kreuz Weinsberg", "motorway_junction"),
        "Fast chargers",
    )

    assert rendered == (
        "📍 Searched around: Kreuz Weinsberg (motorway_junction)\n⚡ Two chargers"
    )


@pytest.mark.asyncio
async def test_agent_forces_final_text_after_tool_round_limit() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [{"name": "check_route", "description": "Check route", "input_schema": {}}]
    bridge.call_tool = AsyncMock(return_value=SimpleNamespace(isError=False, content=[]))
    agent = MobilityAgent(bridge, "model", max_tool_rounds=0)
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock("tool_use", id="1", name="check_route", input={}),
                stop_reason="tool_use",
            ),
            fake_response(FakeBlock("text", text="No verified route result is available.")),
        ]
    )

    answer = await agent.answer("Can this truck use the route?", [])

    assert answer.text == "No verified route result is available."
    assert answer.stop_reason == "end_turn"
    assert answer.tool_rounds == 0
    final_call = agent.client.messages.create.await_args_list[-1].kwargs
    assert "tools" not in final_call


@pytest.mark.asyncio
async def test_agent_retries_factual_answer_without_tool_use() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Find parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(return_value=SimpleNamespace(isError=False, content=[]))
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(FakeBlock("text", text="There are 12 spaces near Stuttgart.")),
            fake_response(FakeBlock("text", text="I need a location to check live data.")),
        ]
    )

    answer = await agent.answer("Parking?", [])

    assert answer.text == "I need a location to check live data."
    assert "Use the tools before answering" in str(
        agent.client.messages.create.await_args_list[-1].kwargs["messages"]
    )


@pytest.mark.asyncio
async def test_agent_suppresses_factual_answer_when_retry_uses_no_tool() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import EMPTY_ANSWER, MobilityAgent

    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Find parking", "input_schema": {}}]
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(FakeBlock("text", text="Stuttgart has parking.")),
            fake_response(FakeBlock("text", text="Stuttgart has 12 spaces.")),
        ]
    )

    answer = await agent.answer("Parking?", [])

    assert answer.text == EMPTY_ANSWER


@pytest.mark.asyncio
async def test_agent_forces_synthesis_after_empty_max_tokens_turn() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(stop_reason="max_tokens"),
            fake_response(FakeBlock("text", text="Please provide a mobility location.")),
        ]
    )

    answer = await agent.answer("Parking information", [])

    assert answer.text == "Please provide a mobility location."
    assert "tools" not in agent.client.messages.create.await_args_list[-1].kwargs


@pytest.mark.asyncio
async def test_agent_resynthesizes_partial_max_tokens_text() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import MobilityAgent

    bridge = MCPBridge()
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(
                FakeBlock("text", text="Partial sentence"), stop_reason="max_tokens"
            ),
            fake_response(FakeBlock("text", text="Please provide a location.")),
        ]
    )

    answer = await agent.answer("Parking information", [])

    assert answer.text == "Please provide a location."


@pytest.mark.asyncio
async def test_agent_returns_clean_off_topic_decline_after_grounding_retry() -> None:
    from mobidata_bw_mcp.telegram_bot.agent import OFF_TOPIC_EN, MobilityAgent

    bridge = MCPBridge()
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(
        side_effect=[
            fake_response(FakeBlock("text", text="Try asking about Stuttgart.")),
            fake_response(FakeBlock("text", text="Ask about Baden-Württemberg.")),
        ]
    )

    answer = await agent.answer("Who won the football world cup?", [])

    assert answer.text == OFF_TOPIC_EN


@pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="requires live source access")
@pytest.mark.asyncio
async def test_real_mcp_server_stdio_bridge() -> None:
    async with MCPBridge() as bridge:
        assert any(tool["name"] == "find_parking" for tool in bridge.tools)