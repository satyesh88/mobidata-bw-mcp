#!/usr/bin/env bash
# Launcher for the Telegram demo bot; dependencies come from the `telegram` extra.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run --extra telegram python -m mobidata_bw_mcp.telegram_bot.main
