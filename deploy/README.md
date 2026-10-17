# Hosted deployment

Runs the MCP server as one Docker container behind a reverse proxy, over Streamable HTTP at `/mcp`,
with API-key authentication and rate limits. Replace `<DOMAIN>` with your public host name; never
commit real host names, addresses or keys.

This is an independent project. It is not affiliated with or endorsed by NVBW or MobiData BW.

## What the hosted server does

| Item | Behaviour |
| --- | --- |
| Endpoints | `POST /mcp` (MCP, authenticated), `GET /health` (open, returns `{"status":"ok"}`) |
| Auth | `Authorization: Bearer <key>`. Only SHA-256 hashes are stored, in `/etc/mobidata-mcp/keys` |
| Limits | 60 requests/minute per key, 600/minute overall (`MOBIDATA_MCP_RATE_PER_KEY`, `MOBIDATA_MCP_RATE_GLOBAL`), request bodies up to 1 MB |
| Host check | DNS-rebinding protection; allowed public host names come from `MOBIDATA_MCP_ALLOWED_HOSTS` |
| Container | Non-root, read-only filesystem, no capabilities, 1 GB memory cap, `restart: unless-stopped`, published on `127.0.0.1:8765` only |
| Startup | Refuses to start without at least one key (unless `--insecure-no-auth`, local testing only) |

### Privacy

The server stores no user data. Each request writes one log line with: time, key name, HTTP method,
JSON-RPC method, tool name, status and latency. It does not log request bodies, queries or locations,
and the application does not log client addresses. Be aware that the reverse proxy and Docker may
keep their own logs (the proxy normally records client IP addresses); configure those to match your
retention policy and tell your users.

## Server setup

Requirements: Docker with the compose plugin, a reverse proxy that can obtain a TLS certificate, and a
DNS record for `<DOMAIN>`.

```bash
# 1. Code
git clone https://github.com/<OWNER>/mobidata-bw-mcp.git /opt/mobidata-bw-mcp
cd /opt/mobidata-bw-mcp

# 2. Public host name the proxy will forward
echo "MOBIDATA_MCP_ALLOWED_HOSTS=<DOMAIN>" > .env

# 3. First API key (printed once; only its hash is stored)
sudo python3 deploy/new-api-key.py <NAME>

# 4. Start
docker compose up -d --build
curl -s http://127.0.0.1:8765/health
```

The first start downloads and indexes the traffic-sign data (roughly 30 to 60 seconds, up to about
700 MB of memory while it builds). `/health` answers immediately; other requests are served normally.

### Reverse proxy

Add one new site for `<DOMAIN>` that proxies to `127.0.0.1:8765`. See
[nginx.example.conf](nginx.example.conf) or [Caddyfile.example](Caddyfile.example). Validate the config
and use a reload, not a restart, so other sites on the same proxy are not interrupted. Streaming
responses must not be buffered (already set in the examples).

### Issuing and revoking keys

```bash
sudo python3 deploy/new-api-key.py alice        # prints the key once
sudoedit /etc/mobidata-mcp/keys                 # delete the line to revoke
```

The key file is re-read automatically within a few seconds; no restart is needed.

### Updating

```bash
cd /opt/mobidata-bw-mcp && git pull && docker compose up -d --build
```

## Connecting clients

URL: `https://<DOMAIN>/mcp`. Header: `Authorization: Bearer <KEY>`.

Claude Code:

```bash
claude mcp add --transport http mobidata https://<DOMAIN>/mcp --header "Authorization: Bearer <KEY>"
```

Claude custom connectors (claude.ai and Claude Desktop): add `https://<DOMAIN>/mcp` as the connector URL.
Whether a client lets you send a static `Authorization` header depends on its version. If it only offers
OAuth, use a client that supports headers (Claude Code above, or a bridge such as `mcp-remote` with
`--header "Authorization: Bearer <KEY>"`).

Python MCP client:

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://<DOMAIN>/mcp"
HEADERS = {"Authorization": "Bearer <KEY>"}


async def main():
    async with streamablehttp_client(URL, headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "find_parking", {"location": "Stuttgart Hauptbahnhof", "limit": 3}
            )
            print(result.content[0].text)


asyncio.run(main())
```

LangGraph (needs `pip install langchain-mcp-adapters langgraph`; see that package's documentation for
the current API):

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "mobidata": {
            "transport": "streamable_http",
            "url": "https://<DOMAIN>/mcp",
            "headers": {"Authorization": "Bearer <KEY>"},
        }
    }
)
tools = await client.get_tools()  # pass these tools to your LangGraph agent
```

## Data licences

Results carry their own source, licence and attribution fields; keep them when showing data to users.
