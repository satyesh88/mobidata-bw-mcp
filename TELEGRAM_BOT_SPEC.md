# Telegram Bot for mobidata-bw-mcp: Build Spec

> **Goal:** Barcamp attendees scan a QR code, message the bot from their own phone, and get live answers from MobiData BW within seconds.
> **The point it proves:** the *same* MCP server that powers Claude Desktop also powers a chat app. "Your data, one standard interface, usable by any AI agent."
> **Status:** demo, not a product. Must be solid by **Mon 19 Oct 2026**. If not, it gets cut.

---

## 1. Architecture

```
Telegram user
   │  (message / shared location)
   ▼
python-telegram-bot (long polling, runs on the MacBook, no public server)
   │
   ▼
Agent loop (Anthropic Messages API with tool use)
   │  tools discovered at startup from ↓
   ▼
MCP client (official `mcp` SDK, stdio) ──► mobidata-bw-mcp server (existing, unchanged)
```

Key decisions:
- **Long polling, not webhooks.** No domain, HTTPS or hosting needed. The bot runs on the laptop at the event (via phone hotspot).
- **Tools come from the MCP server via an MCP client**, not by importing the Python functions directly. That is the whole demo message: any agent can plug in. Start the server once at bot startup with `stdio_client`, keep one `ClientSession`, call `list_tools()`, and convert each tool to the Anthropic tool format (`name`, `description`, `input_schema`).
- **Do not change the MCP server** for the bot. If something is missing, note it in the bot README instead.

## 2. Location in the repo

```
src/mobidata_bw_mcp/telegram_bot/
  __init__.py
  main.py          # entry point, wiring, PTB Application
  agent.py         # Claude tool-use loop
  mcp_bridge.py    # stdio MCP client, tool list + call_tool
  formatting.py    # short replies, HTML escaping, length limits
  limits.py        # per-user rate limit + global daily budget
  watches.py       # proactive alerts (milestone 2)
  texts.py         # /start, /help, privacy note, example questions (EN + DE)
```
- New script in `pyproject.toml`: `mobidata-telegram = "mobidata_bw_mcp.telegram_bot.main:main"`
- New dependencies in an **optional extra** `telegram` (so the MCP server install stays slim): `python-telegram-bot[job-queue]>=21,<23`, `anthropic`, `python-dotenv`.
- Run with: `uv run --extra telegram mobidata-telegram`

## 3. Configuration (`.env`, never committed)

```
TELEGRAM_BOT_TOKEN=...            # from @BotFather
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-haiku-5-5  # cheap + fast default; switch to claude-sonnet-5-5 if answers are weak
DAILY_BUDGET_USD=10               # bot refuses new questions once reached
USER_MSG_LIMIT_PER_HOUR=10
ALLOWED_USER_IDS=                 # optional comma list; empty = public (event mode)
MAX_TOOL_ROUNDS=10
```
- **Add `.env` to `.gitignore` before anything else.** Provide `.env.example` with empty values.
- Also set a **spend limit on the API key in the Anthropic Console** as a second safety net.

## 4. Agent behaviour (system prompt essentials)

- Answer only Baden-Württemberg mobility questions using the tools. For anything else, reply politely in one line and suggest example questions.
- **Phone-sized answers:** at most ~5 short lines, then offer "More?" No tables. Use bullet lines with emoji sparingly (🅿️ ⚡ 🛴 🚧).
- Always state freshness ("live, 3 min ago" / "no live data").
- End every answer with one attribution line: `Daten: MobiData BW® / NVBW und Datengeber`.
- Reply in the user's language (German or English).
- If a location is ambiguous, ask once ("Which Heilbronn location? Hbf, centre, …") or use a shared Telegram location if present.
- Never invent data; if a tool returns nothing, say so.
- Never mention internal tool names to users.

## 5. Features

### Milestone 1: Q&A (must have)
1. **Free-text questions** → agent loop → short HTML reply.
2. **Shared location:** if the user sends a Telegram location, store it for 30 min as "current location" and pass it into the next question ("what's near me?"). Show a hint in /start: "📍 Share your location and ask 'What's near me?'"
3. **/start:** one-line intro, privacy note (see §6), 4 example questions as **inline keyboard buttons** so people can tap instead of type:
   - "🅿️ Parking near Stuttgart Hbf right now"
   - "🛴 E-scooters near Heilbronn Hbf"
   - "⚡ Fast chargers at Weinsberger Kreuz"
   - "🚧 Roadworks around Heilbronn this week"
4. **/help**, **/reset** (clears conversation memory), **/about** (what data, who built it, GitHub link).
5. **Conversation memory:** last 6 messages per chat, in memory only, auto-expire after 30 min.
6. **"Typing…" indicator** while the agent works (`send_chat_action`). Answers may take 5–15 s.

### Milestone 2: proactive alert (the wow; stretch)
`/watch` via natural language, e.g. "Tell me when a fast charger at Weinsberger Kreuz is free" or "Message me if P+R X drops below 20 free spaces".
- Agent turns the request into a structured watch: `{tool, args, condition, description}`. Supported conditions: parking free spaces below/above N, charging available connectors ≥ 1, sharing vehicles within radius ≥ N.
- Checked every 3 min with PTB `JobQueue`; **max 2 watches per user, expire after 2 h**; message the user once when the condition becomes true, then delete the watch.
- `/watches` lists, `/unwatch` removes. In-memory only.
- Demo trick: create a watch whose condition is already true or will flip soon, so the push arrives during the session.

## 6. Safety, cost, privacy

- **Rate limit:** `USER_MSG_LIMIT_PER_HOUR` per user; friendly message when hit.
- **Global budget:** sum input/output tokens from each API `usage` × model price (prices in config), stop accepting questions when `DAILY_BUDGET_USD` is reached ("Demo budget for today is used up 🙂").
- **Tool loop guard:** max `MAX_TOOL_ROUNDS` tool rounds; truncate any single tool result to ~8,000 characters before sending it to the model (some results are large).
- **Timeouts:** 45 s total per question; reply with an apology if exceeded.
- **Privacy:**
  - Don't log message text together with user IDs. Log only a salted hash of the user ID, timestamp, tools used, token counts and latency.
  - /start privacy note: "Your messages are processed by an AI service (Anthropic) to answer them. Nothing is stored after 30 minutes. Shared locations are used only for your current question."
  - No database. Everything is in memory and lost on restart.
- **Group chats:** ignore (private chats only) to avoid accidental spam.

## 7. Formatting details
- Use Telegram **HTML** parse mode (MarkdownV2 escaping is error-prone). Escape all model output, then allow only `<b>`, `<i>`, `<a>`.
- Telegram's message limit is 4096 characters; hard-cap at ~1200 and append "…".
- If the agent produced coordinates for a single best result, optionally send a Telegram **venue/location message** after the text (nice on phones: tap to open in maps).

## 8. Testing
- Unit tests: tool-schema conversion (MCP → Anthropic), HTML escaping/truncation, rate limiter, budget counter, watch condition evaluation.
- Integration test with a fake Telegram update object and the real MCP server via stdio (skipped in CI if no network).
- Manual checklist before the event: the 4 example buttons, a shared location question, a German question, an off-topic question, the rate-limit message, a watch firing, a restart.

## 9. Event setup (README section)
1. Create the bot with @BotFather (`/newbot`), set name "MobiData BW Assistant (Demo)", description, and `/setcommands`: start, help, reset, about, watches.
2. Put the token in `.env`.
3. Generate a QR code for `https://t.me/<bot_username>` and put it on the session slide.
4. At the venue: laptop on phone hotspot, `uv run --extra telegram mobidata-telegram`, keep the terminal visible (shows anonymized live log: "question → tools used → 4.2 s"). That log on the projector is part of the show.
5. After the Barcamp: stop the bot or set `ALLOWED_USER_IDS` so it isn't publicly usable.

### Emergency restart during the demo

1. In the terminal running the bot, press `Ctrl+C` once and wait for it to stop.
2. From the repository directory, restart it:

   ```bash
   cd /Users/satyeshshivam/Documents/mobidata-bw-mcp
   uv run --extra telegram mobidata-telegram
   ```

3. Do not send a demo question until the terminal shows all three lines:

   ```text
   ready tools=16
   Scheduler started
   Application started
   ```

If `Ctrl+C` does not stop the bot, or Telegram reports another polling instance, open a new
terminal and run:

```bash
pkill -f mobidata-telegram
uv run --extra telegram mobidata-telegram
```

Restarting clears the in-memory conversation history and saved locations. It does not change the
bot token or other values in `.env`.

## 10. Order of work
1. `.gitignore` + `.env.example` + extra deps + entry point
2. `mcp_bridge.py` (start server, list tools, call tool) with a small CLI test
3. `agent.py` loop + system prompt
4. `main.py` with /start buttons, text handler, location handler, typing indicator
5. limits + budget + privacy logging
6. Tests, README section
7. **Stretch:** watches

**Cut rule:** if Milestone 1 isn't stable by Sun 18 Oct, skip watches. If Milestone 1 isn't stable by Mon 19 Oct, don't demo the bot.
