import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, TextContent

pytest.importorskip("anthropic")
pytest.importorskip("telegram")

from mobidata_bw_mcp.clients import geocode
from mobidata_bw_mcp.telegram_bot.agent import AgentAnswer, MobilityAgent
from mobidata_bw_mcp.telegram_bot.main import BotHandlers, PendingQuestion, Settings
from mobidata_bw_mcp.telegram_bot.mcp_bridge import MCPBridge


@pytest.fixture
def chat():
    handler = BotHandlers(Settings("token", "model", 10, 30, frozenset(), 6), MCPBridge())
    handler.agent = SimpleNamespace(answer=AsyncMock(return_value=AgentAnswer(
        "Parking source checked.", 2, 1, ["find_parking"], "end_turn", 1, [],
    )))
    message = SimpleNamespace(text="Find me parking near my place", reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_message=message, effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=2),
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(), send_chat_action=AsyncMock(), send_venue=AsyncMock(),
    )
    return handler, update, SimpleNamespace(bot=bot)


@pytest.mark.parametrize("phrase", ["near my place", "near me", "here", "hier", "bei mir"])
async def test_missing_location_requests_keyboard_without_agent_call(chat, phrase):
    handler, update, context = chat
    update.effective_message.text = f"Find me parking {phrase}"
    await handler.question(update, context)
    handler.agent.answer.assert_not_awaited()
    call = context.bot.send_message.await_args
    button = call.kwargs["reply_markup"].keyboard[0][0]
    assert button.text == "📍 Share my location"
    assert button.request_location is True
    assert handler.state.pending(1).question == update.effective_message.text
    assert len(call.args[1].splitlines()) == 1


async def test_saved_location_answers_original_question(chat):
    handler, update, context = chat
    handler.state.set_location(1, 48.77, 9.17)
    await handler.question(update, context)
    handler.agent.answer.assert_awaited_once_with(update.effective_message.text, [], (48.77, 9.17))
    assert "Parking source checked" in context.bot.send_message.await_args.args[1]


async def test_location_delivery_resumes_pending_question_and_removes_keyboard(chat):
    handler, update, context = chat
    await handler.question(update, context)
    original = update.effective_message.text
    update.effective_message.location = SimpleNamespace(latitude=48.77, longitude=9.17)
    await handler.save_location(update, context)
    handler.agent.answer.assert_awaited_once_with(original, [], (48.77, 9.17))
    assert update.effective_message.reply_text.await_args.kwargs["reply_markup"].remove_keyboard
    assert handler.state.pending(1) is None


async def test_typed_address_resumes_original_parking_question(chat):
    handler, update, context = chat
    await handler.question(update, context)
    update.effective_message.text = "Theodor-Heuss-Straße 2, Stuttgart"
    await handler.question(update, context)
    question = handler.agent.answer.await_args.args[0]
    assert "parking" in question
    assert "Theodor-Heuss-Straße 2, Stuttgart" in question
    assert "my place" not in question


async def test_typo_returns_fuzzy_gazetteer_suggestion_without_venue_coordinates(monkeypatch):
    geocode._cache.clear()
    source = AsyncMock(return_value=[])
    monkeypatch.setattr(geocode, "_request", source)
    with pytest.raises(geocode.LocationClarification) as caught:
        await geocode.resolve("momex stuttgart")
    payload = json.loads(str(caught.value))
    assert payload["error"] == "location_clarification"
    assert payload["suggestions"] == [{
        "label": "memox, Theodor-Heuss-Straße 2, Stuttgart",
        "location": "Theodor-Heuss-Straße 2, Stuttgart",
    }]
    source.assert_awaited_once()


async def test_memox_gazetteer_resolves_verified_street_address(monkeypatch):
    geocode._cache.clear()
    source = AsyncMock(return_value=[{
        "lat": "48.777", "lon": "9.176", "display_name": "Theodor-Heuss-Straße 2",
        "type": "building",
    }])
    monkeypatch.setattr(geocode, "_request", source)
    result = await geocode.resolve("memox Stuttgart")
    assert source.await_args.args[1]["q"] == "Theodor-Heuss-Straße 2, Stuttgart"
    assert result.lat == pytest.approx(48.777)
    assert result.label == "memox, Theodor-Heuss-Straße 2, Stuttgart"
    geocode._cache.clear()


async def test_unknown_place_offers_partial_and_city_matches(monkeypatch):
    geocode._cache.clear()
    source = AsyncMock(side_effect=[[], [], [{
        "lat": "48.77", "lon": "9.17", "display_name": "Stuttgart, Baden-Württemberg",
        "type": "city",
    }]])
    monkeypatch.setattr(geocode, "_request", source)
    with pytest.raises(geocode.LocationClarification) as caught:
        await geocode.resolve("unknown-venue Stuttgart")
    assert [call.args[1]["q"] for call in source.await_args_list] == [
        "unknown-venue Stuttgart", "unknown-venue", "Stuttgart",
    ]
    assert json.loads(str(caught.value))["suggestions"][0]["label"].startswith("Stuttgart")


async def test_ambiguous_results_ask_instead_of_selecting_first(monkeypatch):
    geocode._cache.clear()
    monkeypatch.setattr(geocode, "_request", AsyncMock(return_value=[
        {"lat": "48.77", "lon": "9.17", "display_name": "Cafe, North", "type": "cafe"},
        {"lat": "48.87", "lon": "9.27", "display_name": "Cafe, South", "type": "cafe"},
    ]))
    with pytest.raises(geocode.LocationClarification) as caught:
        await geocode.resolve("Cafe unknown")
    assert len(json.loads(str(caught.value))["suggestions"]) == 2
    assert "cafe unknown" not in geocode._cache


class Block:
    type = "tool_use"
    id = "parking-1"
    name = "find_parking"
    input = {"location": "momex stuttgart"}

    def model_dump(self, **kwargs):
        return {"type": self.type, "id": self.id, "name": self.name, "input": self.input}


def model_response():
    return SimpleNamespace(
        content=[Block()], stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
    )


async def test_mcp_geocoding_error_reaches_suggestion_buttons_and_selection(chat, monkeypatch):
    handler, update, context = chat
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Parking", "input_schema": {}}]
    error = geocode.LocationClarification("momex stuttgart", [{
        "label": "memox, Theodor-Heuss-Straße 2, Stuttgart",
        "location": "Theodor-Heuss-Straße 2, Stuttgart",
    }])
    bridge.call_tool = AsyncMock(return_value=CallToolResult(isError=True, content=[
        TextContent(type="text", text="Error executing tool find_parking: " + str(error)),
    ]))
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(return_value=model_response())
    handler.agent = agent
    update.effective_message.text = "Find me parking near momex stuttgart"
    await handler.question(update, context)
    agent.client.messages.create.assert_awaited_once()
    call = context.bot.send_message.await_args
    assert call.args[1] == "Did you mean memox, Theodor-Heuss-Straße 2, Stuttgart?"
    buttons = call.kwargs["reply_markup"].inline_keyboard
    assert len(buttons) == 1
    update.callback_query = SimpleNamespace(data=buttons[0][0].callback_data, answer=AsyncMock())
    handler.agent = SimpleNamespace(answer=AsyncMock(return_value=AgentAnswer(
        "Parking checked.", 2, 1, ["find_parking"], "end_turn", 1, [],
    )))
    await handler.example(update, context)
    question = handler.agent.answer.await_args.args[0]
    assert "parking" in question and "Theodor-Heuss-Straße 2, Stuttgart" in question
    assert "momex" not in question


async def test_tool_exception_explains_what_failed_without_leaking_private_details(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(side_effect=RuntimeError("private-token-123"))
    agent = MobilityAgent(bridge, "model", max_tool_rounds=1)
    agent.client.messages.create = AsyncMock(side_effect=[model_response(), SimpleNamespace(
        content=[SimpleNamespace(type="text", text="The lookup had a problem.")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=2, output_tokens=1),
    )])
    answer = await agent.answer("Find parking near Stuttgart", [])
    assert "parking data" in answer.text
    assert "please try again" in answer.text
    assert "private-token-123" not in answer.text
    assert "lookup failed" not in answer.text


async def test_reset_and_expiry_clear_pending_question(chat):
    handler, update, context = chat
    handler.state._pending[1] = PendingQuestion(
        "parking", expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert handler.state.pending(1) is None
    handler.state._pending[1] = PendingQuestion("parking")
    await handler.reset(update, context)
    assert handler.state.pending(1) is None


async def test_empty_geocoder_and_suggestion_source_failure_still_ask_for_address(monkeypatch):
    geocode._cache.clear()
    from mobidata_bw_mcp.clients.http import SourceError

    monkeypatch.setattr(geocode, "_request", AsyncMock(side_effect=[
        [], SourceError("offline"), SourceError("offline"),
    ]))
    with pytest.raises(geocode.LocationClarification) as caught:
        await geocode.resolve("missing venue")
    assert json.loads(str(caught.value))["suggestions"] == []


async def test_geocoding_clarification_survives_fastmcp_error_wrapper(monkeypatch):
    from mcp.server.fastmcp.exceptions import ToolError

    from mobidata_bw_mcp.server import mcp
    from mobidata_bw_mcp.telegram_bot.agent import _location_clarification

    geocode._cache.clear()
    monkeypatch.setattr(geocode, "_request", AsyncMock(return_value=[]))
    with pytest.raises(ToolError) as caught:
        await mcp.call_tool("find_parking", {"location": "momex stuttgart"})
    payload = _location_clarification(str(caught.value))
    assert payload["suggestions"][0]["location"] == "Theodor-Heuss-Straße 2, Stuttgart"


async def test_shared_location_replaces_unresolved_venue_for_pending_search(chat):
    handler, update, context = chat
    handler.state._pending[1] = PendingQuestion(
        "Find parking near momex stuttgart", "momex stuttgart",
    )
    update.effective_message.location = SimpleNamespace(latitude=48.77, longitude=9.17)
    await handler.save_location(update, context)
    call = handler.agent.answer.await_args
    assert "parking" in call.args[0]
    assert "momex" not in call.args[0]
    assert call.args[2] == (48.77, 9.17)


async def test_stale_suggestion_button_cannot_replace_new_pending_question(chat):
    handler, update, context = chat
    handler.state._pending[1] = PendingQuestion("New parking question")
    update.callback_query = SimpleNamespace(data="place:00000000:0", answer=AsyncMock())
    await handler.example(update, context)
    handler.agent.answer.assert_not_awaited()
    assert handler.state.pending(1).question == "New parking question"
    assert "expired" in context.bot.send_message.await_args.args[1]


async def test_source_failure_still_helpful_if_followup_model_call_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    bridge = MCPBridge()
    bridge.tools = [{"name": "find_parking", "description": "Parking", "input_schema": {}}]
    bridge.call_tool = AsyncMock(side_effect=RuntimeError("private upstream details"))
    agent = MobilityAgent(bridge, "model")
    agent.client.messages.create = AsyncMock(side_effect=[
        model_response(), RuntimeError("model offline"), RuntimeError("model offline"),
    ])
    answer = await agent.answer("Parking near Stuttgart", [])
    assert "parking data" in answer.text
    assert "please try again" in answer.text
    assert "private" not in answer.text
