"""Replay a fixed departures question locally with the bot's configured model and skill.

Uses the API credentials in .env; never sends Telegram messages or logs message bodies.
"""
import argparse
import asyncio
import hashlib
import json
import logging
from datetime import datetime

from dotenv import load_dotenv

from mobidata_bw_mcp.telegram_bot import agent as module
from mobidata_bw_mcp.telegram_bot.main import Settings
from mobidata_bw_mcp.telegram_bot.mcp_bridge import MCPBridge
from mobidata_bw_mcp.telegram_bot.tool_logging import logged_arguments


async def replay(question: str, request_time: str) -> None:
    load_dotenv('.env')
    settings = Settings.from_environment()
    module._berlin_now = lambda: datetime.fromisoformat(request_time)
    print(json.dumps({
        'model': settings.anthropic_model,
        'skill_sha256': hashlib.sha256(module._SKILL_PATH.read_bytes()).hexdigest(),
        'request_time': request_time,
    }), flush=True)
    async with MCPBridge() as bridge:
        original = bridge.call_tool

        async def traced(name, arguments):
            print(json.dumps({'tool': name, 'arguments': logged_arguments(arguments)},
                             ensure_ascii=False), flush=True)
            return await original(name, arguments)

        bridge.call_tool = traced
        agent = module.MobilityAgent(
            bridge, settings.anthropic_model, settings.max_tool_rounds,
            settings.anthropic_workspace_id,
        )
        answer = await agent.answer(question, [])
        print(json.dumps({'answer': answer.text, 'tools': answer.tools_used},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', default=(
        'Heilbronn Hbf, Monday 19 October 2026, 09:00–09:30. '
        'Show all departures, including Stadtbahn, with stops and wheelchair information.'
    ))
    parser.add_argument('--request-time', default='2026-10-18T12:00:00+02:00')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(replay(args.question, args.request_time))
