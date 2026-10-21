# MobiData BW MCP Server

**Your data, one standard interface, usable by any AI agent.**

A source-available [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for public mobility data in Baden-Württemberg from [MobiData BW](https://mobidata-bw.de/). It gives any AI agent the same set of tools for live parking, charging and sharing status, roadworks, traffic messages, traffic signs, scheduled and live public transport, journey planning, station accessibility, and route checks for trucks.

Plug it into Claude, ChatGPT/OpenAI, Cursor, VS Code, Claude Code, LangChain, or your own bot or app. You don't have to write any integration code per client.

> This is an independent project. It is not affiliated with or endorsed by NVBW or MobiData BW.

---

## What you can reuse

| Part | What it is | Where |
|---|---|---|
| **MCP server** | 19 tools over MobiData BW data, usable from any MCP client | `src/mobidata_bw_mcp/` |
| **Agent skill** | Instructions that teach an agent *how* to use the tools well: which tool for which question, freshness, caveats, attribution | `skill/SKILL.md` |
| **Reference bot** | A Telegram bot built on the server, which you can copy for WhatsApp, Slack or your own app | `src/mobidata_bw_mcp/telegram_bot/` |

## Pick your path

| I want to... | Go to |
|---|---|
| Try it in Claude, Cursor or VS Code **without installing anything** | [1. Use the hosted server](#1-use-the-hosted-server) |
| Run it **on my own computer**, no key needed | [2. Run it locally](#2-run-it-locally) |
| Make my agent **answer better** with these tools | [3. Add the skill](#3-add-the-skill) |
| Build it **into my own app, bot or agent** | [4. Build it into your product](#4-build-it-into-your-product) |
| Host it **on my own server** | [5. Self-host](#5-self-host) |

Try asking: *"Which fast chargers near Weinsberger Kreuz are free right now?"*

---

## 1. Use the hosted server

| | |
|---|---|
| URL | `https://mcp.routeiq.de/mcp` (Streamable HTTP) |
| Auth | `Authorization: Bearer <KEY>` |
| Status | `https://mcp.routeiq.de/health` (open) |
| Limits | 60 requests per minute per key |

**Getting a key:** open a [GitHub issue](https://github.com/satyesh88/mobidata-bw-mcp/issues/new) titled "API key request" and say who you are and what you want to build. The maintainer will contact you to hand over the key privately. **Never post a key in an issue, a commit or a screenshot.** Each person or app gets its own key, and any key can be revoked at any time.

The examples below use `<KEY>` or the environment variable `MOBIDATA_MCP_KEY`.

### Claude Code

```bash
claude mcp add --transport http mobidata-bw https://mcp.routeiq.de/mcp \
  --header "Authorization: Bearer <KEY>"
claude mcp list
```

### Claude (web, desktop and phone)

1. Go to **Customize → Connectors → Add custom connector**.
2. URL: `https://mcp.routeiq.de/mcp`. Authentication: **No sign-in**.
3. Under **Request headers**, add `authorization` with the value `Bearer <KEY>`. Include the word `Bearer` and the space.
4. In a chat, turn it on with **+ → Connectors**.

Request headers are a beta feature that only some organisations have. If you don't see that section, use Claude Code or the `mcp-remote` bridge below instead. Details are in Anthropic's guide [Add a connector that isn't in the directory](https://claude.com/docs/connectors/custom/add-unlisted). The connector also works from the phone app, because Claude's servers make the connection.

### Cursor

`~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project):

```json
{
  "mcpServers": {
    "mobidata-bw": {
      "url": "https://mcp.routeiq.de/mcp",
      "headers": { "Authorization": "Bearer <KEY>" }
    }
  }
}
```

### VS Code (Copilot agent mode)

`.vscode/mcp.json`. VS Code asks you for the key, so it isn't stored in the file:

```json
{
  "servers": {
    "mobidata-bw": {
      "type": "http",
      "url": "https://mcp.routeiq.de/mcp",
      "headers": { "Authorization": "Bearer ${input:mobidata-key}" }
    }
  },
  "inputs": [
    { "type": "promptString", "id": "mobidata-key", "description": "MobiData MCP key", "password": true }
  ]
}
```

### Claude Desktop config file, or any client that only supports local servers

Bridge to the hosted server with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) (needs Node.js):

```json
{
  "mcpServers": {
    "mobidata-bw": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.routeiq.de/mcp", "--header", "Authorization:${MOBIDATA_AUTH}"],
      "env": { "MOBIDATA_AUTH": "Bearer <KEY>" }
    }
  }
}
```

---

## 2. Run it locally

No key and no account are needed. The server runs on your machine and calls MobiData BW directly.

**Requirements:** Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Run straight from GitHub, without cloning
uvx --from git+https://github.com/satyesh88/mobidata-bw-mcp mobidata-bw-mcp

# Or clone it (for development)
git clone https://github.com/satyesh88/mobidata-bw-mcp
cd mobidata-bw-mcp
uv sync
uv run mobidata-bw-mcp
```

### Claude Desktop

Open **Settings → Developer → Edit Config** and add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mobidata-bw": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/satyesh88/mobidata-bw-mcp", "mobidata-bw-mcp"]
    }
  }
}
```

Restart Claude Desktop. **mobidata-bw** then appears under the tools icon. If you cloned the repo, use `"command": "uv", "args": ["--directory", "/path/to/mobidata-bw-mcp", "run", "mobidata-bw-mcp"]` instead.

If Claude Desktop can't find `uvx`, use its full path (`which uvx`).

### Claude Code

```bash
claude mcp add mobidata-bw -- uvx --from git+https://github.com/satyesh88/mobidata-bw-mcp mobidata-bw-mcp
```

### Cursor and VS Code

Use the same `command` and `args` as in the Claude Desktop example. In VS Code, put them under `"servers"` with `"type": "stdio"`. The repo already contains a ready `.vscode/mcp.json` for development.

---

## 3. Add the skill

The MCP server gives an agent the **tools**. The skill teaches it **how to use them**:
- which tool fits which question
- to always state how fresh the data is
- how to read accessibility surveys
- which caveats to mention
- how to attribute MobiData BW

The skill only helps when the MCP server (hosted or local) is also connected.

**Skill release v0.3.0** includes station-wide departure windows (up to 30 rows, including
Stadtbahn stops at Heilbronn Hbf/Willy-Brandt-Pl.), explicit timeout wording, correct
wheelchair flags, and conservative BFRK edge-to-track handling. It also covers accessible
parking versus public transport comparisons and answer-driven navigation.

Use an updated MCP server exposing `time_from`, `time_to` and `platform_only` on
`get_departures`. Update a self-hosted server before installing this skill; see
[Updating the hosted services](deploy/UPDATING.md). The skill ZIP contains instructions,
not the server or its credentials.

**Easiest:** download [mobidata-bw.zip for v0.3.0](https://github.com/satyesh88/mobidata-bw-mcp/releases/download/v0.3.0/mobidata-bw.zip) and upload it under **Customize → Skills → + → Upload a skill**.

### Claude (web and desktop): no terminal needed

1. Turn on **Settings → Capabilities → Code execution and file creation**.
2. Download **[mobidata-bw.zip](https://github.com/satyesh88/mobidata-bw-mcp/releases/latest/download/mobidata-bw.zip)**. Don't unzip it.
3. Go to **Customize → Skills → + → Create skill → Upload a skill** and choose the ZIP.
4. Start a **new chat** and ask: *"Is Heilbronn Hbf step-free?"*

More detail: [Use skills in Claude](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

### Claude Code

Unzip [mobidata-bw.zip](https://github.com/satyesh88/mobidata-bw-mcp/releases/latest/download/mobidata-bw.zip) into `~/.claude/skills/` (you get `~/.claude/skills/mobidata-bw/SKILL.md`), or use the commands under [Build it yourself](#build-it-yourself). To use it in only one project, put it in `.claude/skills/mobidata-bw/SKILL.md` inside that project instead.

### Your own agent (any model)

Add the text of [`skill/SKILL.md`](skill/SKILL.md) to your system prompt. The Telegram bot does exactly this, together with today's date and the channel name.

### Build it yourself

Use this if the download link doesn't work, or if you want the latest `main` instead of the last release.

Claude Code, straight from the repository. macOS / Linux:
```bash
mkdir -p ~/.claude/skills/mobidata-bw
curl -fsSL https://raw.githubusercontent.com/satyesh88/mobidata-bw-mcp/main/skill/SKILL.md \
  -o ~/.claude/skills/mobidata-bw/SKILL.md
```

Windows (PowerShell):
```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\skills\mobidata-bw" | Out-Null
Invoke-WebRequest https://raw.githubusercontent.com/satyesh88/mobidata-bw-mcp/main/skill/SKILL.md `
  -OutFile "$HOME\.claude\skills\mobidata-bw\SKILL.md"
```

Build the upload ZIP from a clone with Python 3 (also works on Windows with `python`):
```bash
python3 scripts/build_skill.py
```

Upload `dist/mobidata-bw.zip`. The builder verifies that the archive contains exactly
`mobidata-bw/SKILL.md` and matches the current source. It uses fixed ZIP timestamps so
repeated builds of the same skill produce the same archive.

Tagged releases (`v*`) run the same builder and attach `mobidata-bw.zip` to the GitHub
release. The [latest-release download](https://github.com/satyesh88/mobidata-bw-mcp/releases/latest/download/mobidata-bw.zip)
tracks the newest published release.

<details>
<summary>Build the ZIP by hand (no terminal)</summary>

1. Open [`skill/SKILL.md`](skill/SKILL.md) on GitHub. Click **Raw**, then save the page as `SKILL.md`.
2. Create a folder named exactly `mobidata-bw` and put `SKILL.md` inside it.
3. Compress the **folder**. On Mac, right-click it and choose **Compress**. On Windows, right-click it and choose **Send to → Compressed (zipped) folder**.
4. Upload `mobidata-bw.zip` under **Customize → Skills → + → Upload a skill**. The ZIP must contain `mobidata-bw/SKILL.md`.
</details>

---

## 4. Build it into your product

Your app talks to an LLM, the LLM calls the tools, and the server returns MobiData BW data. Any language with an MCP SDK works (Python, TypeScript, Java, Kotlin, C#, Swift, Go, Rust and others). The pattern is always the same: Streamable HTTP, the URL, and one `Authorization` header.

> **Never ship the key inside a mobile or browser app.** Let the app call your own backend. The backend holds the key and talks to the MCP server, the way the bots do.

### Python (official MCP SDK)

```python
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HEADERS = {"Authorization": f"Bearer {os.environ['MOBIDATA_MCP_KEY']}"}

async def main():
    async with streamablehttp_client("https://mcp.routeiq.de/mcp", headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()          # give these to any LLM
            result = await session.call_tool(
                "find_parking", {"location": "Stuttgart Hauptbahnhof", "limit": 3}
            )
            print(result.content[0].text)

asyncio.run(main())
```

### Anthropic API (MCP connector, no client code)

```python
import os, anthropic

response = anthropic.Anthropic().beta.messages.create(
    model="<MODEL>",
    max_tokens=1024,
    betas=["mcp-client-2025-11-20"],
    mcp_servers=[{
        "type": "url",
        "url": "https://mcp.routeiq.de/mcp",
        "name": "mobidata-bw",
        "authorization_token": os.environ["MOBIDATA_MCP_KEY"],
    }],
    tools=[{"type": "mcp_toolset", "mcp_server_name": "mobidata-bw"}],
    messages=[{"role": "user", "content": "Which chargers near Weinsberger Kreuz are free now?"}],
)
print(response.content)
```

Beta names change over time, so check the [MCP connector docs](https://docs.claude.com/en/docs/agents-and-tools/mcp-connector) for the current one.

### OpenAI API (Responses API)

```python
import os
from openai import OpenAI

resp = OpenAI().responses.create(
    model="<MODEL>",
    tools=[{
        "type": "mcp",
        "server_label": "mobidata_bw",
        "server_url": "https://mcp.routeiq.de/mcp",
        "authorization": os.environ["MOBIDATA_MCP_KEY"],
        "require_approval": "never",
    }],
    input="Where can I park near Stuttgart Hauptbahnhof right now?",
)
print(resp.output_text)
```

The ChatGPT app itself expects OAuth for custom MCP servers, so this API-key server isn't a drop-in there today. Use the API as shown above.

### LangChain / LangGraph

[`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/) loads the tools from the same URL and header.

### Telegram bot (reference implementation)

A complete bot in `src/mobidata_bw_mcp/telegram_bot/`:
- uses Claude with this server's tools and the skill
- answers in German or English
- sends up to three answer-driven navigation buttons and a pin with the same short facility name
- retrieves one merged station-complex timetable for an explicit time window, up to 30 departures
- runs parallel tools with per-tool timeouts and a 75-second total deadline
- shows a progress message after 8 seconds and preserves partial results when a source fails
- enforces per-user and daily-budget limits

```bash
uv sync --extra telegram
cp .env.example .env     # set TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY
./run-telegram.sh        # starts its own local MCP server (stdio)
```

To use the hosted server instead, set `MCP_SERVER_URL` and `MCP_SERVER_KEY` in `.env`. To run it as a service, see [deploy/README.md](deploy/README.md#telegram-bot-optional). Run only one copy per bot token.

### WhatsApp, Slack and other chat apps

The agent loop (`MobilityAgent` and `MCPBridge`) doesn't depend on Telegram:
1. Receive the message through the platform's webhook.
2. Call `await agent.answer(text, history)`. Create `MCPBridge()` once and run `await bridge.start()`.
3. Send `answer.text` back, formatted for that platform (for WhatsApp: plain text and `*bold*`).

For WhatsApp, check Meta's current Business messaging and AI policies before you launch.

---

## 5. Self-host

[deploy/README.md](deploy/README.md) covers running your own HTTPS endpoint (a small VPS is enough):
- systemd units
- the nginx reverse proxy
- API keys
- the optional bot

Updates are covered in [deploy/UPDATING.md](deploy/UPDATING.md).

**Keys:**
- Create one key per person or app with `python3 deploy/new-api-key.py <NAME> --owner <service user>`.
- To revoke a key, delete its line in `/etc/mobidata-mcp/keys`. No restart is needed.
- The server stores only key hashes.
- Limits are 60 requests per minute per key and 600 for the whole server.
- The server logs only the key name, MCP method, tool and status. It never logs request content or locations.

Use `--insecure-no-auth` only for local testing. Ask NVBW about fair use before you host it for the public.

---

## Tools

| Tool | Purpose |
|---|---|
| `search_datasets`, `get_dataset` | Find datasets, their current resources and licences |
| `list_layers`, `query_layer` | Explore and query GeoServer WFS layers |
| `find_parking` | Nearest car, bicycle, motorcycle or truck parking with live capacity, with paging |
| `find_accessible_parking` | Nearby disabled parking spaces from ParkAPI and BFRK station surveys |
| `stop_accessibility` | Surveyed step-free access, platforms, tactile guidance, lifts, ramps, toilets and parking |
| `find_charging` | Nearby chargers by power and current availability |
| `find_sharing` | Sharing stations and free-floating vehicles |
| `find_transit`, `get_departures` | Nearby stops and scheduled departures |
| `get_live_departures`, `plan_transit_journey` | TRIAS live predictions and A-to-B public transport journeys (requires access) |
| `get_roadworks` | Roadworks active on a given date |
| `find_traffic_signs` | Nearby traffic signs, including truck restrictions |
| `find_traffic_messages` | Current accidents, congestion, closures and obstructions (DATEX II) |
| `check_route` | Roadworks, traffic messages and truck signs along a route |
| `data_health` | Which feeds are fresh, which are stale (older than 30 min), and which have no live feed |
| `about` | Sources and caveats (also available as the MCP resource `mobidata://about`) |

[TOOLS.md](TOOLS.md) is the full reference: every parameter, result field, source, licence and caveat.

## Optional TRIAS public transport access

The MCP server supports live departure predictions and end-to-end journey planning through
NVBW's [TRIAS service](https://mobidata-bw.de/dataset/trias). Configure the credentials on
the **MCP server**, not in tool arguments or the agent prompt:

```dotenv
TRIAS_URL=https://efa-bw.de/trias
TRIAS_REQUESTOR_REF=<requestor key supplied by NVBW>
```

For local development, keep these in the ignored `.env` file and launch with
`uv run --env-file .env mobidata-bw-mcp`. Hosted deployments use the MCP service's
protected environment file; see [deployment instructions](deploy/README.md#trias-access).

`get_live_departures` distinguishes scheduled and estimated times, delays, cancellations
and platform changes. If TRIAS is unavailable, it can return explicitly labelled GTFS
scheduled data. `get_departures` retains its existing scheduled-only interface.
`plan_transit_journey` accepts an origin, destination and either departure or arrival time,
plus optional wheelchair preferences and transfer limits. Coordinate journeys request
up to 15 minutes of walking access; live departures discover up to three stop groups
within 500 m. These limits can exclude options. Requested preferences do not
prove end-to-end accessibility or current lift operation; BFRK surveys remain separate evidence.

The server now exposes 19 tools. Fares, ticket booking and background journey alerts are
outside this integration. Identical successful TRIAS responses are cached for 30 seconds; live coverage varies
by operator. Never commit credentials or XML requests containing the requestor key.

## Example questions

- Which roadworks or truck restrictions are on the route from Heilbronn via Weinsberg to Eberstadt next Wednesday?
- How fresh is the live parking data in Stuttgart and Heilbronn, and which records are stale?
- Which shared bikes and scooters are available within 1 km of Heilbronn Hbf right now?
- Which accessible parking spaces are within 1 km of Stuttgart Hbf, and which have live availability?
- Is Heilbronn Hbf step-free? What are its lift, platform and tactile-guidance details?
- Which chargers of at least 150 kW near Weinsberger Kreuz have a free connector now?
- Which MobiData BW datasets cover bicycles, and under which licences?

## Data and trust

Every result names its source endpoint, licence (or missing licence), attribution, timestamp where one exists, and freshness warnings.

**Sources:**
- MobiData BW CKAN catalogue
- GeoServer WFS
- ParkAPI v3
- the GTFS PostgREST API
- EFA-BW TRIAS departures and journey planning (with configured access)
- the daily traffic-sign export
- roadworks GeoJSON
- DATEX II traffic messages
- the BFRK accessibility surveys
- OpenStreetMap Nominatim for geocoding

Licences vary by dataset, most often CC BY 4.0 and Datenlizenz Deutschland.

**Caveats:**
- `get_departures` is scheduled GTFS data. TRIAS live predictions depend on operator coverage; a missing prediction does not confirm on-time running. Scheduled fallback is labelled.
- BFRK accessibility surveys come from different years and may be outdated, so check the survey year in the result. Object coordinates are deliberately offset by about 1.5–4 m.
- BFRK lift records describe the surveyed equipment, not whether a lift is working right now.
- Traffic-sign data is not legally binding, and municipal coverage varies.
- Supplementary signs such as "Lieferverkehr frei" are not included, so restrictions may have exceptions.
- Nominatim geocoding is cached and rate-limited to follow its usage policy.
- Read the MobiData BW terms of use before you publish or host this server.

**Attribution:** Daten: MobiData BW® / NVBW und Datengeber.

## Development

```bash
uv run ruff check .
uv run pytest
uv run python scripts/selftest.py                        # one live call per source
npx @modelcontextprotocol/inspector uv run mobidata-bw-mcp
```

Tests and examples use only public or synthetic data, never customer data. Issues and pull requests are welcome. See the [contributor guidelines](CONTRIBUTING.md) and [design document](docs/DESIGN.md).

## How this was built

Designed, tested and maintained by Satyesh Shivam (RouteIQ). Built with AI-assisted development tools; architecture, data-source decisions, honesty rules and real-world testing were done by the maintainer. Data: MobiData BW® / NVBW und Datengeber.

## Licence

The current project is available under [PolyForm Noncommercial 1.0.0](LICENSE).
Noncommercial use is permitted under its terms. Commercial use outside those permissions
requires a separate written commercial licence from Satyesh Shivam (RouteIQ), which may
involve a fee. Request one through a [GitHub issue](https://github.com/satyesh88/mobidata-bw-mcp/issues/new)
titled "Commercial licence request"; describe the intended use without posting confidential information.
Opening an issue or receiving an API key does not itself grant a commercial licence.

PolyForm expressly permits use by government institutions, educational institutions and
certain other noncommercial organisations; see the licence for the full permissions.
This project is source-available rather than OSI open source.

**Earlier releases:** versions through commit `4826a89cec2ce86a67db76ffd7bf00a1dbc096dd`,
including tag `v0.3.0`, were released under Apache-2.0. Existing Apache rights, including
commercial-use rights, remain in effect for that previously released material. This
change applies prospectively and does not revoke those rights. The former licence is
preserved in [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).

The source datasets and third-party dependencies keep their own licences and attribution
requirements. This project licence does not restrict independent use of MobiData BW data.
