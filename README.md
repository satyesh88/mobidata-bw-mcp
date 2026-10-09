# MobiData BW MCP Server

Your data, one standard interface, usable by any AI agent.

This open-source [Model Context Protocol](https://modelcontextprotocol.io/) server gives Claude Desktop, Cursor, Claude Code, and custom agents a consistent interface to public mobility data from [MobiData BW](https://mobidata-bw.de/). It combines live parking, charging and sharing status, roadworks, traffic signs, scheduled transit, catalogue discovery, and route-level computation.

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

Streamable HTTP is available for development with `uv run mobidata-bw-mcp --transport http --port 8000`. Ask NVBW about fair use before publicly hosting it.

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

## Tools

| Tool | Purpose |
|---|---|
| `search_datasets`, `get_dataset` | Discover datasets, current resources, and licences |
| `list_layers`, `query_layer` | Explore and query GeoServer WFS layers |
| `find_parking` | Nearby car, bicycle, or truck parking and live capacity |
| `find_charging` | Nearby chargers by power and current availability |
| `find_sharing` | Sharing stations and free-floating vehicles |
| `find_transit`, `get_departures` | Nearby stops and scheduled departures |
| `get_roadworks` | Roadworks active on a selected date |
| `find_traffic_signs` | Nearby signs, including truck restrictions |
| `check_route` | Roadworks and truck signs intersecting a supplied route |
| `data_health` | Computed freshness of parking, charging, and sharing feeds |
| `about` | Server sources and caveats |

The same metadata as `about` is available at the MCP resource `mobidata://about`.

## Demo questions

- Here is tomorrow's synthetic Heilbronn to Bad Rappenau route for a 26 t, 4.0 m truck. Which roadworks or truck restrictions intersect it?
- How fresh is realtime parking data in Stuttgart or Heilbronn, and which records are stale?
- Which shared bikes and scooters are available within 1 km of Heilbronn Hbf right now?
- Which chargers of at least 150 kW near Weinsberger Kreuz have a free connector now?
- Which MobiData datasets cover bicycles, and under which licences?

## Data and trust

Sources include the MobiData BW CKAN catalogue, GeoServer WFS, ParkAPI v3, GTFS PostgREST API, daily traffic-sign export, roadworks GeoJSON, and OpenStreetMap Nominatim. Dataset licences vary, commonly CC BY 4.0 and Datenlizenz Deutschland licences. Every result identifies its endpoint, licence or licence status, attribution, timestamp where available, and freshness warnings.

Important caveats:

- Public transport is scheduled GTFS only, not realtime.
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