# MobiData BW MCP Server — Build Spec

> **Pitch:** "Your data, one standard interface, usable by any AI agent."
> An open-source MCP server that exposes MobiData BW® (the open mobility data platform of Baden-Württemberg, run by NVBW) as tools any AI agent can use — Claude Desktop, Cursor, Claude Code, or a custom agent built with LangGraph / OpenAI Agents SDK / the Claude API.

- **Owner:** Satyesh Shivam (RouteIQ)
- **Deadline:** working demo by **Tue 20 Oct 2026** (MobiData BW Barcamp, Wed 21 Oct 2026, memox Stuttgart)
- **Repo name:** `mobidata-bw-mcp` (public on GitHub, licence MIT or EUPL-1.2 — EUPL matches MobiData's own `ipl-orchestration` repo)

---

## 1. Goals and non-goals

### Goals
1. **One interface over many APIs.** Hide the differences between CKAN, GeoServer WFS, ParkAPI v3, OCPI/OCPDB, GBFS and the GTFS PostgREST API behind a small set of consistent, well-described tools.
2. **Answers ChatGPT cannot give from web search.** Every showcase tool must use *live status* or *computation over many records* (see §7 demo questions). Plain "where is X" lookups are not the point.
3. **Trustworthy output.** Every result carries source, licence/attribution, data timestamp and a freshness flag.
4. **Easy to adopt.** `uvx mobidata-bw-mcp` + 6 lines of Claude Desktop config. Works locally (stdio) and can later be hosted (Streamable HTTP).

### Non-goals (v0.1)
- No routing engine of our own (callers pass a route geometry — see `check_route`).
- No real-time public transport (TRIAS / GTFS-RT have separate terms of use) — scheduled GTFS only.
- No DATEX II / TN-ITS parsing (JSON/GeoJSON equivalents exist).
- No writes, no user accounts, no API keys.
- **No customer data** (e.g. Kurz / CANDIS exports) anywhere in the repo, tests or demo.

---

## 2. Tech stack

- Python ≥ 3.11, managed with **uv**
- **`mcp` official Python SDK (FastMCP)** — `from mcp.server.fastmcp import FastMCP`
- `httpx` (async) for HTTP, `pydantic` for tool I/O models
- `shapely` for geometry (buffers, distance, intersections) + `pyproj` only if needed for metre buffers (or use a local equirectangular approximation — fine for BW scale)
- `cachetools` (TTLCache) for in-memory caching
- Tests: `pytest`, `pytest-asyncio`, `respx` (HTTP mocking with recorded fixtures)

Project layout:
```
mobidata-bw-mcp/
  pyproject.toml
  README.md
  SPEC.md
  src/mobidata_bw_mcp/
    server.py          # FastMCP app, tool registration
    config.py          # base URLs, TTLs, limits, user agent
    clients/
      ckan.py          # catalog
      wfs.py           # GeoServer WFS (generic)
      parkapi.py       # ParkAPI v3
      gtfs.py          # GTFS PostgREST
      static_files.py  # roadworks geojson, traffic signs geojson (download + cache)
      geocode.py       # Nominatim
    tools/
      discovery.py     # search_datasets, get_dataset, list_layers
      spatial.py       # query_layer
      parking.py, charging.py, sharing.py, transit.py, roadworks.py, signs.py
      route_check.py   # check_route (showcase)
      health.py        # data_health (showcase)
    models.py          # Location, BBox, ResultEnvelope, ...
    geo.py             # haversine, bbox from radius, buffers
  skill/SKILL.md       # Claude skill: how to answer mobility questions with these tools
  scripts/selftest.py  # hits every live endpoint once, prints PASS/FAIL table
  tests/
```

---

## 3. Data sources (verified from mobidata-bw.de, 9–10 Oct 2026)

All public, no API key required (except the traffic-sign *API*, see 3.7 — use the open file instead).

### 3.1 Catalog — CKAN 2.11
- Base: `https://mobidata-bw.de/api/3/action/`
- `package_search?q=<text>&rows=<n>` — search the ~146 datasets
- `package_show?id=<slug>` — description, `license_id`/`license_title`, `metadata_modified`, `resources[]` (each with `url`, `format`, `name`)
- Use `package_show` to resolve **current** resource URLs at runtime instead of hard-coding dated file names (e.g. Bedarfsumleitungen XLSX is named `YYYY-MM-DD_...xlsx`).

### 3.2 GeoServer WFS — the backbone
- Endpoint: `https://api.mobidata-bw.de/geoserver/MobiData-BW/ows`
- `service=WFS&request=GetFeature&typeName=<layer>&outputFormat=application/json`
- Supports `maxFeatures`/`count`, `bbox`, `CQL_FILTER` (CQL filters are used on the official CSV links, e.g. `form_factor = 'bicycle'`).
- Layers (13), with **geometry attribute name** (needed for spatial CQL like `DWITHIN`/`BBOX`):

| Layer | Title | Geometry attr | Key attributes |
|---|---|---|---|
| `MobiData-BW:roadworks` | Arbeitsstellen | `geometry` (line) | id, type, subtype, starttime, endtime, description, street, direction |
| `MobiData-BW:charge_points` | E-Ladesäulen | `geometry` | name, operator_name, address, city, max_electric_power, chargepoint_available_count, chargepoint_charging_count, chargepoint_inoperative_count, chargepoint_outoforder_count, status_last_updated, realtime_data_outdated |
| `MobiData-BW:park-api_car` | Parkplätze | `geometry` | name, type, capacity, realtime_free_capacity, capacity_truck, realtime_free_capacity_truck, max_height, has_realtime_data, realtime_data_updated_at, realtime_data_outdated, official_region_code |
| `MobiData-BW:park-api_car_lines` | Parkplätze (Linien) | `geometry` (line) | on-street parking segments |
| `MobiData-BW:park-api_car_polygons` | Parkplätze (Polygone) | `geometry` (polygon) | |
| `MobiData-BW:park-api_bicycle` | Fahrradabstellanlagen | `geometry` | capacity, realtime_free_capacity, is_covered, type |
| `MobiData-BW:sharing_stations` | Sharing-Stationen | `geometry` | feed_id, name, num_bicycles_available, num_cars_available, num_scooters_available, num_cargo_bicycles_available, num_mopeds_available, last_reported, realtime_data_outdated |
| `MobiData-BW:sharing_vehicles` | Free-Floating Sharing-Fahrzeuge | `geometry` | feed_id, form_factor, propulsion_type, current_range_meters, last_reported, realtime_data_outdated |
| `MobiData-BW:transit_stops` | Haltesteige | `stop_loc` | stop_id, stop_name, wheelchair_boarding, parent_station |
| `MobiData-BW:transit_stations_with_served_routes` | Haltestellen und Bahnhöfe | `centroid` | station_id, station_name, routes |
| `MobiData-BW:transit_shapes_with_routes` | ÖPNV-Linien | `shape` | route_names, agency_name |
| `MobiData-BW:radvis_cycle_network` | RadNETZ-BW | `wkb_geometry` | |
| `MobiData-BW:bicycle_service_points` | Radservicepunkte | `geometry` | |

- ⚠️ **Axis order:** WFS 1.1/2.0 with EPSG:4326 may use lat/lon order; WFS 1.0.0 uses lon/lat. Pick one version, then **verify with a known point** (Heilbronn Hbf ≈ lat 49.1427, lon 9.2069) in `selftest.py` before trusting any bbox query.
- `list_layers` should read `GetCapabilities` (cache 24 h) so new layers appear automatically.

### 3.3 ParkAPI v3 (parking)
- Base: `https://api.mobidata-bw.de/park-api/api/public/v3/`
- `GET parking-sites` — params: `lat`, `lon`, `radius` (metres), or `lat_min/lat_max/lon_min/lon_max`; `purpose` (CAR, BIKE, MOTORCYCLE, ITEM); `type`; `name`; `official_region_code`; `limit`, `start` (paginate via `next_offset`/`next_path`); `realtime_data_updated_at_since` etc.
- `GET parking-sites/{id}`, `GET parking-sites/{id}/history`, `GET sources`
- Note: realtime is treated as outdated if older than 30 min (`calculate_has_realtime_data`).
- OpenAPI: `https://api.mobidata-bw.de/park-api/documentation/public.json`

### 3.4 Charging (OCPDB)
- Prefer the WFS layer `charge_points` (already has per-location available/charging/out-of-order counts + freshness).
- Deep detail (EVSEs, connectors, tariffs): OCPI 3.0 at `https://api.mobidata-bw.de/ocpdb/api/ocpi/3.0/{locations|evses|connectors}`, tariffs at `.../api/public/ocpi/3.0/tariffs`. Query params are **not documented** on the dataset page — inspect `https://api.mobidata-bw.de/ocpdb/documentation/public.json` before using; v0.1 can skip OCPI.

### 3.5 Sharing (GBFS)
- Manifest: `https://api.mobidata-bw.de/sharing/gbfs/v3/manifest.json` (113 systems; each has v2.3 and v3.0 discovery URLs, e.g. `.../sharing/gbfs/v3/stadtmobil_stuttgart/gbfs`)
- For spatial queries use WFS `sharing_stations` / `sharing_vehicles` (no need to walk 113 feeds). Use GBFS only for `list_sharing_systems` and operator metadata.

### 3.6 Roadworks
- GeoJSON (whole state, one file): `https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json` → download, cache 15 min, filter locally with shapely.
- Also WFS layer `roadworks` (use if the file is large or for bbox queries).
- Covers planned and current works on federal (B), state (L) and district (K) roads.

### 3.7 Traffic signs (truck restrictions)
- Open full export: `https://mobidata-bw.de/daten/portal/VZ-Daten/signs.geojson` (daily) → download, cache 24 h, build a spatial index (shapely STRtree).
- The **API/WFS** for signs requires registration by email (verkehrszeichenkataster@vm.bwl.de) — not needed for v0.1.
- **Field schema is undocumented** → first task: download the file, inspect properties, find the sign-code field (StVO numbers). Truck-relevant StVO signs to look for: **253** (Verbot für Kfz > 3,5 t), **262** (tatsächliche Masse), **263** (Achslast), **264** (Breite), **265** (Höhe), **266** (Länge), **277** (Überholverbot Lkw).
- Caveats to surface in every result: not legally binding; coverage varies by municipality; **supplementary signs (Zusatzzeichen, e.g. "Lieferverkehr frei") are not included yet** — so a restriction may have exceptions we can't see.

### 3.8 Scheduled public transport (GTFS)
- PostgREST API: `https://api.mobidata-bw.de/gtfs/` — tables include `stops`, `routes`, `trips`, `stop_times`, `arrivals_departures` (columns: stop_id, stop_name, station_name, route_short_name, trip_headsign, date, arrival_time, departure_time, t_departure, wheelchair_boarding …), `connections`.
- PostgREST filter syntax, e.g. `arrivals_departures?station_id=eq.<id>&date=eq.2026-10-21&t_departure=gte.<iso>&order=t_departure&limit=20`.
- ⚠️ Data is regenerated daily but available "the day after next" — dates near today may be missing; handle empty results gracefully.
- Full GTFS zip (weekly): `https://www.nvbw.de/fileadmin/user_upload/service/open_data/fahrplandaten_ohne_liniennetz/bwgesamt.zip` (not needed in v0.1).

### 3.9 Official detours (Bedarfsumleitungen)
- XLSX from the Verkehrsministerium, resolve via `package_show?id=bedarfsumleitungen-baden-wurttemberg`. Column structure undocumented → stretch goal only.

### 3.10 Geocoding
- Nominatim (`https://nominatim.openstreetmap.org/search?format=jsonv2&q=...&countrycodes=de`), **usage policy: max 1 request/second, custom User-Agent required**, cache results. Restrict/bias to Baden-Württemberg viewbox. Make the geocoder pluggable.

### 3.11 Licences and attribution
- Licences vary per dataset (mostly **CC BY 4.0** or **Datenlizenz Deutschland – Namensnennung 2.0**; some dl-de/zero, ODbL). Read `license_title` from CKAN `package_show` and include it in results.
- Every response includes `attribution: "Daten: MobiData BW® / NVBW und Datengeber, <licence>"`.
- The general terms-of-use page could not be read automatically → **read https://mobidata-bw.de/pages/nutzungsbedingungen manually before publishing** and ask NVBW at the Barcamp about rate limits / fair use for a hosted server.

---

## 4. Conventions for all tools

- **Location input:** every location-based tool accepts `location` as either a place string (geocoded) or `{lat, lon}`. Return the resolved coordinates in the result.
- **Coordinates:** WGS84, `lat`/`lon` as named fields (never bare arrays).
- **Limits:** default `limit=20`, hard max 200. Results sorted by distance when a location is given (`distance_m` field).
- **Result envelope** (pydantic model):
  ```json
  {
    "query": {...resolved inputs...},
    "count": 12,
    "truncated": false,
    "items": [...],
    "source": {"dataset": "gebuendelte-parkdaten-bw", "endpoint": "...", "licence": "...", "attribution": "..."},
    "data_timestamp": "2026-10-21T08:14:00+02:00",
    "warnings": ["3 of 12 sites have outdated realtime data (>30 min)"]
  }
  ```
- **Compact items:** only fields an agent needs; drop nulls; translate German enum values only where it helps (keep originals too).
- **Freshness:** whenever a record has `realtime_data_outdated` or a last-updated timestamp, expose `is_live: bool` and `age_minutes`.
- **Errors:** never raise raw stack traces to the client; return a clear message ("ParkAPI timed out; try a smaller radius") and log details to stderr (stdio servers must not print to stdout).
- **Caching (TTL):** realtime 60 s · roadworks 15 min · layer list / capabilities 24 h · traffic signs file 24 h · geocoding 7 d · CKAN 1 h.
- **Politeness:** `User-Agent: mobidata-bw-mcp/<version> (+https://github.com/<user>/mobidata-bw-mcp)`; max 4 concurrent requests; timeouts 20 s; one retry with backoff.
- **Tool descriptions** are part of the product — write them for an LLM: when to use, units, limits, caveats. Keep each under ~80 words.

---

## 5. Tools (v0.1)

### Discovery
1. **`search_datasets(query: str, limit: int = 10)`** → title, slug, short description, licence, last modified, formats. *(CKAN package_search)*
2. **`get_dataset(dataset_id: str)`** → full description, licence, resources (name, format, url), last modified. *(CKAN package_show)*
3. **`list_layers()`** → WFS layer names, titles, geometry attribute. *(GetCapabilities, cached)*

### Generic
4. **`query_layer(layer: str, location?|bbox?, radius_m: int = 1000, filter: str | None = None, limit: int = 20)`** → GeoJSON-ish features (properties + lat/lon or simplified geometry). Validate `layer` against `list_layers`. `filter` is CQL; sanitize (allow-list operators/fields, no semicolons). This is the "one interface" escape hatch.

### Domain (opinionated, agent-friendly)
5. **`find_parking(location, radius_m=1000, purpose="CAR", only_free=False, truck=False)`** → name, type, capacity, free now, is_live, distance, max_height. `truck=True` → only sites with `capacity_truck > 0`. *(ParkAPI v3, fallback WFS)*
6. **`find_charging(location, radius_m=2000, min_power_kw=0, only_available=False)`** → name, operator, max kW, available/total, out-of-order count, is_live, distance. *(WFS charge_points)*
7. **`find_sharing(location, radius_m=500, kind="any|bicycle|car|scooter|cargo_bicycle|moped")`** → stations with counts + free-floating vehicles (with range for e-vehicles), operator (feed_id), rental link. *(WFS sharing_stations + sharing_vehicles)*
8. **`find_transit(location, radius_m=500)`** + **`get_departures(stop_or_station_id, date?, from_time?, limit=10)`** → scheduled departures. *(WFS transit_stops/stations + GTFS PostgREST)*
9. **`get_roadworks(location?|bbox?, radius_m=5000, active_on: date | None = today)`** → street, type, description, start/end, direction, geometry summary. *(roadworks GeoJSON)*
10. **`find_traffic_signs(location?|bbox?, radius_m=500, sign_codes: list[str] | None = None, truck_relevant_only=False)`** → sign code, meaning, value if present, coordinates. Always include the caveats from §3.7. *(signs.geojson)*

### Showcase (the "ChatGPT can't do this" tools)
11. **`check_route(route: GeoJSON LineString | list[{lat,lon}], buffer_m: int = 30, date: date | None = today, vehicle: {"weight_t": float, "height_m": float} | None = None)`**
    - Input is a **route geometry supplied by the caller** (e.g. RouteIQ, or any router). If only stop points are given, warn that straight lines between stops are an approximation.
    - Finds roadworks intersecting the buffered route that are active on `date`, and truck-relevant signs within the buffer; if `vehicle` is given, evaluate 262/265 values against weight/height.
    - Output: list of **issues** ordered along the route (`km_from_start`, kind, severity, street, description, source), plus a summary ("2 roadworks, 1 height limit 3.8 m — vehicle is 4.0 m ⚠️").
    - Optional dev helper (clearly labelled demo-only, off by default): fetch a route from the public OSRM demo server to turn stop points into a road geometry. Not for production use.
12. **`data_health(region: str | None = None, dataset: "parking|charging|sharing|all" = "all")`**
    - Computes freshness/coverage over raw feeds: % of parking sites with live data, sites with outdated realtime (> 30 min), charge points `realtime_data_outdated`, sharing feeds whose `last_reported` is stale, counts per `official_region_code` / city.
    - Output: per-source table + top issues. This is the "value back to NVBW" demo.

### Meta
13. **`about()`** → server version, data sources, licences, caveats, contact. Also expose as MCP **resource** `mobidata://about`.

---

## 6. Skill (`skill/SKILL.md`)

A Claude skill shipped in the repo that teaches an agent to use the server well:
- Ask for / infer a location; prefer `find_*` tools, use `query_layer` only when no domain tool fits.
- Always state data freshness ("live as of 08:14" vs "no live data") and cite MobiData BW + licence.
- For trucks/logistics: use `check_route`; explain sign caveats (Zusatzzeichen missing, not legally binding).
- For "is the data good?" questions: use `data_health`.
- Answer in the user's language (German or English).
- Present maps when the client supports artifacts (GeoJSON → simple Leaflet page).

---

## 7. Demo questions (each must work live by 20 Oct)

Pass the filter: *could ChatGPT answer this with web search? If yes, it's not a demo.*

1. **Truck tour check (RouteIQ story):** "Here is tomorrow's tour for a 26 t skip truck, 4.0 m high: [synthetic route through Heilbronn → Neckarsulm → Bad Rappenau]. Any roadworks or truck restrictions along it?" → `check_route`
2. **Data health (NVBW story):** "How fresh is the realtime parking data in Stuttgart and Heilbronn right now? Which sources look stale?" → `data_health`
3. **Live, computed:** "How many shared e-scooters and bikes are available within 1 km of Heilbronn Hbf right now, by operator — and how many have > 50 % battery?" → `find_sharing`
4. **Live charging:** "Fast chargers ≥ 150 kW within 10 km of Weinsberger Kreuz with a free connector right now?" → `find_charging`
5. **Discovery:** "Which datasets does MobiData have about bicycles, and what licence do they use?" → `search_datasets` + `get_dataset`

Use a **synthetic** tour only (public addresses / landmarks), never customer data.

---

## 8. Testing

- `scripts/selftest.py`: calls every client once against live endpoints with Heilbronn/Stuttgart coordinates; prints a PASS/FAIL table with latency and item counts; also asserts WFS axis order using Heilbronn Hbf. Run before every demo.
- Unit tests with `respx` fixtures recorded from real responses (store small trimmed samples in `tests/fixtures/`).
- Test `check_route` with a hand-made LineString and a fixture roadwork that intersects it, plus one that doesn't, plus one outside the active date.
- MCP-level test: start server via stdio with the MCP Inspector (`npx @modelcontextprotocol/inspector uv run mobidata-bw-mcp`) and call each tool.

---

## 9. Install / usage (README content)

```bash
uvx mobidata-bw-mcp          # once published to PyPI
# or from source
uv run mobidata-bw-mcp
```

Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mobidata-bw": {
      "command": "uv",
      "args": ["--directory", "/Users/<you>/Documents/mobidata-bw-mcp", "run", "mobidata-bw-mcp"]
    }
  }
}
```
Claude Code: `claude mcp add mobidata-bw -- uv --directory <path> run mobidata-bw-mcp`

Later: `--transport http --port 8000` for a hosted Streamable-HTTP endpoint (ask NVBW about fair use first).

README must include: what it is, demo questions, tool list, data sources + licences, caveats, "not affiliated with NVBW" disclaimer (unless they endorse it).

---

## 10. Milestones (to 20 Oct)

| # | When | Deliverable |
|---|---|---|
| M0 | Sat 10 – Sun 11 Oct | Repo scaffold, config, `selftest.py` hitting CKAN, WFS (axis order!), ParkAPI, roadworks file, signs file, GTFS, Nominatim. **Inspect signs.geojson schema and roadworks fields; record fixtures.** |
| M1 | Mon 12 – Tue 13 | Discovery tools + `query_layer` + result envelope + caching. Wire into Claude Desktop. |
| M2 | Wed 14 – Fri 16 | `find_parking`, `find_charging`, `find_sharing`, `get_roadworks`, `find_traffic_signs`, `find_transit`/`get_departures`. |
| M3 | Sat 17 – Sun 18 | `check_route` + `data_health` + SKILL.md. Demo questions 1–5 run end-to-end. |
| M4 | Mon 19 – Tue 20 | README, GitHub publish, QR code, 60–90 s **backup screen recording** of all demos, session pitch in the Barcamp Padlet. |

**Cut order if time runs short:** transit/departures → OSRM helper → `data_health` per-region breakdown → `query_layer` CQL filter. Never cut: `check_route`, freshness/attribution in outputs, selftest, backup video.

---

## 11. Open questions (ask NVBW at the Barcamp)
- Rate limits / fair use for a publicly hosted MCP server?
- signs.geojson: coverage around Heilbronn-Franken; when will Zusatzzeichen be included?
- Roadworks feed: update frequency; municipal (inner-city) roadworks planned?
- Truck parking and truck-restriction data (height/weight) in the pipeline?
- Interest in listing the project in the MobiData BW Showroom?
