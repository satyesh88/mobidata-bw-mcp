# MobiData BW MCP Server

Your data, one standard interface, usable by any AI agent.

This open-source [Model Context Protocol](https://modelcontextprotocol.io/) server gives Claude, Cursor, VS Code, Claude Code, the OpenAI and Anthropic APIs, chat bots, apps, and custom agents a consistent interface to public mobility data from [MobiData BW](https://mobidata-bw.de/). It combines live parking, charging and sharing status, roadworks, traffic signs, scheduled transit, catalogue discovery, and route-level computation.

> This independent project is not affiliated with or endorsed by NVBW or MobiData BW.

## Install

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
# From PyPI once published
uvx mobidata-bw-mcp

# From this repository
uv sync
uv run mobidata-bw-mcp
```

For a hosted endpoint (Streamable HTTP with an API key), the Telegram or WhatsApp bots, ChatGPT, mobile apps and other clients, see [Hosted server and other clients](#hosted-server-and-other-clients) below.

### Claude Desktop

```json
{
	"mcpServers": {
		"mobidata-bw": {
			"command": "uv",
			"args": [
				"--directory",
				"/Users/<you>/Documents/mobidata-bw-mcp",
				"run",
				"mobidata-bw-mcp"
			]
		}
	}
}
```

Claude Code:

```bash
claude mcp add mobidata-bw -- uv --directory /path/to/mobidata-bw-mcp run mobidata-bw-mcp
```

VS Code users can start or debug the included `mobidata-bw` server from `.vscode/mcp.json`.

## Hosted server and other clients

The server speaks MCP, so any MCP client can use it. There are two ways to connect:

| | Local (stdio) | Hosted (Streamable HTTP) |
|---|---|---|
| How | The client starts the server on your machine (see [Install](#install)) | The client calls `https://<DOMAIN>/mcp` |
| Needs | Python 3.11+ and [uv](https://docs.astral.sh/uv/) | A running instance and an API key |
| Auth | None | `Authorization: Bearer <KEY>` |
| Best for | Claude Desktop, Cursor, VS Code, Claude Code on your own computer | Claude on the web and phone, cloud agents, bots, apps, teammates |

There is no public instance with open keys. To get a hosted endpoint, [run your own](deploy/README.md) (a small server is enough; updates are in [deploy/UPDATING.md](deploy/UPDATING.md)) or ask the operator of an instance for a key. Ask NVBW about fair use before hosting it for the public. Use `--insecure-no-auth` only for local testing.

Examples below use `https://<DOMAIN>/mcp` and a key in `MOBIDATA_MCP_KEY`. Only the Python client example was run against this server. The others follow the vendors' documentation, so test them with your account and check the vendor's current docs if a setting has moved.

### Claude on the web, desktop and phone (custom connector)

1. Open Customize, then Connectors, then Add custom connector.
2. Enter `https://<DOMAIN>/mcp` as the URL and choose "No sign-in" for Authentication.
3. Under Request headers add `Authorization` with the value `Bearer <KEY>` (include the word `Bearer` and the space).
4. Turn the connector on per chat from the + menu.

Claude's servers connect to your endpoint, so it must be reachable from the public internet. Request headers are a beta feature that is limited to some organizations; if the section is missing, your organization does not have it yet. See Anthropic's guide [Add a connector that isn't in the directory](https://claude.com/docs/connectors/custom/add-unlisted).

### Claude Code

```bash
claude mcp add --transport http mobidata-bw https://<DOMAIN>/mcp --header "Authorization: Bearer <KEY>"
claude mcp list
```

### Cursor and VS Code

Cursor, in `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project):

```json
{
  "mcpServers": {
    "mobidata-bw": {
      "url": "https://<DOMAIN>/mcp",
      "headers": { "Authorization": "Bearer <KEY>" }
    }
  }
}
```

VS Code, in `.vscode/mcp.json`, asking for the key instead of storing it:

```json
{
  "servers": {
    "mobidata-bw": {
      "type": "http",
      "url": "https://<DOMAIN>/mcp",
      "headers": { "Authorization": "Bearer ${input:mobidata-key}" }
    }
  },
  "inputs": [
    { "type": "promptString", "id": "mobidata-key", "description": "MobiData MCP key", "password": true }
  ]
}
```

### Clients that only support local (stdio) servers

Bridge to the hosted server with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "mobidata-bw": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://<DOMAIN>/mcp", "--header", "Authorization:${MOBIDATA_AUTH}"],
      "env": { "MOBIDATA_AUTH": "Bearer <KEY>" }
    }
  }
}
```

### ChatGPT and the OpenAI API

OpenAI's models can call remote MCP servers from the Responses API:

```python
import os
from openai import OpenAI

resp = OpenAI().responses.create(
    model="<MODEL>",
    tools=[{
        "type": "mcp",
        "server_label": "mobidata_bw",
        "server_url": "https://<DOMAIN>/mcp",
        "authorization": os.environ["MOBIDATA_MCP_KEY"],
        "require_approval": "never",
    }],
    input="Where can I park near Stuttgart Hauptbahnhof right now?",
)
print(resp.output_text)
```

The `authorization` field is documented as an OAuth token that is sent as a bearer token; this server accepts any key issued by `deploy/new-api-key.py` in that position.

In the ChatGPT app (Plugins, Add custom MCP server), OpenAI's documentation describes OAuth sign-in for custom servers. A static API key is not documented there, so this API-key server is not a drop-in for the ChatGPT app today. Use the API as above, or put an OAuth-capable gateway in front.

### Anthropic API

```python
import os
import anthropic

response = anthropic.Anthropic().beta.messages.create(
    model="<MODEL>",
    max_tokens=1024,
    betas=["mcp-client-2025-11-20"],
    mcp_servers=[{
        "type": "url",
        "url": "https://<DOMAIN>/mcp",
        "name": "mobidata-bw",
        "authorization_token": os.environ["MOBIDATA_MCP_KEY"],
    }],
    tools=[{"type": "mcp_toolset", "mcp_server_name": "mobidata-bw"}],
    messages=[{"role": "user", "content": "Which chargers near Weinsberger Kreuz are free now?"}],
)
print(response.content)
```

The MCP connector supports tool calls only and needs a public HTTPS URL.

### Your own Python agent

```python
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

HEADERS = {"Authorization": f"Bearer {os.environ['MOBIDATA_MCP_KEY']}"}

async def main():
    async with streamablehttp_client("https://<DOMAIN>/mcp", headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "find_parking", {"location": "Stuttgart Hauptbahnhof", "limit": 3}
            )
            print(result.content[0].text)

asyncio.run(main())
```

For LangGraph or LangChain, [`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/) loads the tools from the same URL and header; see [deploy/README.md](deploy/README.md). Any MCP SDK (TypeScript, Java, Kotlin, C#, Swift, Go, Rust, Ruby, PHP) works the same way: Streamable HTTP, URL above, one `Authorization` header.

### Telegram bot

The repository contains a Telegram bot (`src/mobidata_bw_mcp/telegram_bot`) that answers mobility questions with Claude and this server's tools, sends navigation buttons and a location pin, and enforces per-user and daily-budget limits.

```bash
uv sync --extra telegram
cp .env.example .env            # set TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY
./run-telegram.sh               # starts its own local MCP server (stdio)
```

To make it use a hosted server instead, set `MCP_SERVER_URL=https://<DOMAIN>/mcp` (or `http://127.0.0.1:8765/mcp` on the same host) and `MCP_SERVER_KEY` in `.env`. Running it as a service is covered in [deploy/README.md](deploy/README.md#telegram-bot-optional). Keep one running copy per bot token.

### WhatsApp bot

WhatsApp has no MCP support of its own, so a bot is a small web service between WhatsApp and the model. The agent loop in the Telegram bot (`MobilityAgent` and `MCPBridge`) does not depend on Telegram, so it can be reused:

1. Register a number with the WhatsApp Business Cloud API and point its webhook at your service.
2. For each incoming text, call `await agent.answer(text, history)` (create `MCPBridge()` once and `await bridge.start()`; set `MCP_SERVER_URL` and `MCP_SERVER_KEY` for a hosted server).
3. Send `answer.text` back with the Cloud API's send-message call. Adapt the channel rules in the system prompt and format for WhatsApp (plain text, `*bold*`).

This is a sketch, not a shipped feature. Check Meta's current WhatsApp Business messaging and AI-assistant policies before launching.

### iOS and Android

- **Claude app:** add the custom connector above on the web; Claude's servers make the connection, so it also works when you chat from the phone app.
- **Your own app:** never put the API key in the app. Let the app call your own backend, which holds the key and talks to the MCP server (as the bots do). An official MCP SDK for Swift or Kotlin is an option when you control the key distribution.

### Key handling

- Give each client or person its own key (`python3 deploy/new-api-key.py <NAME> --owner <service user>`), so one can be revoked without affecting the others. Revoke by deleting the line in `/etc/mobidata-mcp/keys`; no restart is needed.
- The server limits each key to 60 requests a minute and the whole server to 600, and logs only the key name, MCP method, tool and status, not requests or locations.
- Treat a key like a password: environment variables or a secret store, never in Git, screenshots, client-side code or chat.

## Tools

| Tool | Purpose |
|---|---|
| `search_datasets`, `get_dataset` | Discover datasets, current resources, and licences |
| `list_layers`, `query_layer` | Explore and query GeoServer WFS layers |
| `find_parking` | Nearest-first car, bicycle, motorcycle, or truck parking and live capacity, with paging |
| `find_accessible_parking` | Nearby disabled spaces from ParkAPI plus BFRK station surveys |
| `stop_accessibility` | Surveyed step-free access, platforms, tactile guidance, lifts, ramps, toilets, and parking |
| `find_charging` | Nearby chargers by power and current availability |
| `find_sharing` | Sharing stations and free-floating vehicles |
| `find_transit`, `get_departures` | Nearby stops and scheduled departures |
| `get_roadworks` | Roadworks active on a selected date |
| `find_traffic_signs` | Nearby signs, including truck restrictions |
| `find_traffic_messages` | Current accidents, congestion, closures, and obstructions (DATEX II) |
| `check_route` | Roadworks, traffic messages, and truck signs intersecting a supplied route |
| `data_health` | Fresh, stale (>30 min), and no-live-feed groups with age evidence; parking defaults to off-street |
| `about` | Server sources and caveats |

The same metadata as `about` is available at the MCP resource `mobidata://about`.

See [TOOLS.md](TOOLS.md) for the full reference: every parameter, result field, source, licence and caveat.

## Demo questions

- Here is tomorrow's synthetic Heilbronn to Bad Rappenau route for a 26 t, 4.0 m truck. Which roadworks or truck restrictions intersect it?
- How fresh is realtime parking data in Stuttgart or Heilbronn, and which records are stale?
- Which shared bikes and scooters are available within 1 km of Heilbronn Hbf right now?
- Which accessible parking spaces are within 1 km of Stuttgart Hbf, and which have live availability?
- Is Waldenburg Bahnhof step-free, and what are its lift, ramp, platform, and tactile-guidance details?
- Which chargers of at least 150 kW near Weinsberger Kreuz have a free connector now?
- Which MobiData datasets cover bicycles, and under which licences?

## Data and trust

Sources include the MobiData BW CKAN catalogue, GeoServer WFS, ParkAPI v3, GTFS PostgREST API, daily traffic-sign export, roadworks GeoJSON, and OpenStreetMap Nominatim. Dataset licences vary, commonly CC BY 4.0 and Datenlizenz Deutschland licences. Every result identifies its endpoint, licence or licence status, attribution, timestamp where available, and freshness warnings.

Important caveats:

- Public transport is scheduled GTFS only, not realtime.
- BFRK accessibility surveys were collected in different years and may be outdated; inspect the returned survey year. Object coordinates are deliberately offset by about 1.5-4 m.
- BFRK elevator records describe surveyed infrastructure, not live operating status. DB FaSta status is not queried unless separately configured.
- Traffic-sign data is not legally binding and municipal coverage varies.
- Supplementary signs such as `Lieferverkehr frei` are not included, so restrictions may have exceptions.
- Nominatim geocoding is cached and rate-limited to comply with its public usage policy.
- Read the MobiData BW terms of use before publishing or hosting this server.

## Development

```bash
uv run ruff check .
uv run pytest
uv run python scripts/selftest.py
npx @modelcontextprotocol/inspector uv run mobidata-bw-mcp
```

The self-test calls each live source once and verifies WFS longitude/latitude axis order around Heilbronn Hbf. Tests and examples use only public or synthetic data, never customer data.

## Licence

Server source code is released under the [Apache License 2.0](LICENSE). Source datasets retain their own licences and attribution requirements.