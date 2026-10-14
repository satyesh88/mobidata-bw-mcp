---
name: mobidata-bw
description: Use live and scheduled Baden-Württemberg mobility data through the MobiData BW MCP server.
---

# MobiData BW mobility answers

1. Ask for or infer a location. Pass a place string or explicit `lat` and `lon`.
2. Prefer `find_parking`, `find_charging`, `find_sharing`, and `find_transit`. Use `query_layer` only when no domain tool fits.
3. Use `find_accessible_parking` for disabled spaces and `stop_accessibility` for surveyed stop infrastructure.
4. For truck or logistics routes, use `check_route` with caller-supplied route geometry and vehicle dimensions.
5. For feed quality questions, use `data_health`, including its parking accessibility coverage.
6. State whether records are live, stale, have no live feed, scheduled, or surveyed; include the returned timestamp or survey year.
7. Cite MobiData BW / NVBW, the data providers, and the returned licence.
8. For BFRK results, repeat that surveys may be outdated, coordinates are offset 1.5-4 m, and elevator status is not live.
9. Explain that traffic-sign data is not legally binding, coverage varies, and supplementary signs are missing.
10. Answer in the user's language, German or English.
11. When the client supports artifacts, render returned GeoJSON on a simple Leaflet map.