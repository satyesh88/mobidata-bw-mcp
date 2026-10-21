# MobiData BW MCP design

## Goals

The server gives MCP clients a consistent, read-only interface to public mobility data
in Baden-Württemberg. Its 19 tools cover discovery, spatial queries, parking, charging,
sharing, scheduled departures, surveyed accessibility, traffic events, signs and route
checks. Results carry provenance and limitations so clients can distinguish observations,
schedules and missing information.

The [tool reference](../TOOLS.md) defines the current tool parameters and result fields.
The [README](../README.md) covers installation and client integration.

## Non-goals

The server does not modify upstream datasets, manage bookings or process customer data.
GTFS scheduled departures are not real-time predictions; TRIAS provides predictions only
where operator data is available. Accessibility surveys do not establish
current lift operation or guarantee an accessible journey. Traffic-sign and route findings
are advisory, not legally binding navigation instructions. Coverage depends on each source.

## Data sources

| Source | Purpose |
| --- | --- |
| MobiData BW CKAN catalogue | Dataset discovery, resources, licences and attribution |
| MobiData BW GeoServer WFS | Spatial layers, charging, sharing and transit stops |
| ParkAPI v3 | Parking facilities, capacities and available live occupancy |
| NVBW BFRK CSV surveys | Station and stop accessibility, platform edges, lifts and ramps |
| MobiData BW GTFS PostgREST API | Scheduled departures and stop hierarchies |
| NVBW EFA-BW TRIAS 1.2 | Live departures and A-to-B journeys with configured requestor access |
| Roadworks GeoJSON | Planned and active roadworks |
| DATEX II traffic messages | Accidents, congestion, closures and obstructions |
| Traffic-sign export | Surveyed signs and truck restrictions |
| OpenStreetMap Nominatim | Cached, rate-limited place lookup with a Baden-Württemberg bias |
| OpenRouteService, when configured | Routing between waypoints for route checks |

[Data coverage](../DATA_COVERAGE.md) describes source coverage and gaps. Dataset licences
remain separate from the PolyForm Noncommercial 1.0.0 licence of the current project.

## Architecture

The Python application uses the official MCP SDK and FastMCP. Async source clients handle
HTTP access and caching; domain modules normalize records and implement tool behaviour.
Pydantic models define shared values and result envelopes. Spatial operations use Shapely.
The same tool registrations serve local stdio clients and authenticated HTTP clients.

The Telegram reference agent discovers tools through MCP and loads the
[agent skill](../skill/SKILL.md). The skill describes answer composition and honesty rules;
it is separate from the source adapters and tool schemas.

Caches reduce repeated downloads and lookups. Startup prewarming runs in the background
and tolerates individual source failures. Cache freshness and source timestamps remain
distinct: a recently fetched record can still contain an old observation.

## Tool design principles and conventions

### Stable interfaces and bounded queries

Tools have focused names, typed inputs and descriptions suitable for client discovery.
The catalogue tools expose metadata; spatial tools accept place names or explicit WGS84
coordinates. Distances use metres and charging power uses kilowatts. Limits and pagination
are explicit in the tool schemas. Resolved locations remain visible in query metadata.

Station departures merge the station complex, including configured sibling stop groups,
into a time-sorted list. Explicit platform-only requests retain their narrower scope.
Time windows bound timetable queries. A source timeout is distinct from an empty result.

TRIAS uses XML requests over HTTPS with a server-side requestor key. Live departures
retain scheduled and estimated times separately; a failure can fall back to explicitly
labelled GTFS schedules. Journey planning supports departure or arrival constraints and
wheelchair preferences without asserting verified accessibility. Short response caching
is separate from observation freshness. The original scheduled tool remains compatible.

### Result envelopes and provenance

Data results share `query`, `count`, `items`, `truncated`, `source`, `data_timestamp` and
`warnings`. Pagination supplies `next_cursor` where supported. Source metadata includes
endpoint, licence and attribution; missing licence information remains visible.
Unavailable values are omitted or marked unknown rather than replaced with invented values.

Live status depends on an observation timestamp and freshness checks. Survey dates,
scheduled service dates and live observation times retain their separate meanings.
Warnings explain stale feeds, incomplete coverage, partial results and approximations.

### Accessibility and uncertainty

GTFS wheelchair flags normalize as `0` → `unknown`, `1` → `accessible`, and
`2` → `not_accessible`, for both trips and stops. Unknown means no accessibility info in
the timetable. Surveyed platform-edge IDs do not establish track numbers: explicit track
labels are required. Surveyed infrastructure does not establish its current operating status.

Parking availability for a facility does not establish that its accessible spaces are free.
Route checks based on straight lines instead of a routing service identify that approximation.
Client answers preserve these distinctions and name missing information.

## Validation and contribution

Tests use synthetic records or public fixtures and mock source failures, caching,
pagination and normalization. Live diagnostic scripts are separate from the offline suite.
The [contributor guidelines](../CONTRIBUTING.md) define development commands and data rules.
The current project is licensed under [PolyForm Noncommercial 1.0.0](../LICENSE), with
separate written licences available for commercial use outside its permissions.
The [README licence section](../README.md#licence) records the earlier Apache release boundary.
