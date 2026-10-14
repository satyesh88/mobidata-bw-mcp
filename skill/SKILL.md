---
name: mobidata-bw
description: Use live and scheduled Baden-Württemberg mobility data through the MobiData BW MCP server.
---

# MobiData BW mobility answers

1. Ask for or infer a location. Pass a place string or explicit `lat` and `lon`.
2. Prefer `find_parking`, `find_charging`, `find_sharing`, and `find_transit`. Use `query_layer` only when no domain tool fits.
3. For truck or logistics routes, use `check_route` with caller-supplied route geometry and vehicle dimensions.
4. For feed quality questions, use `data_health`.
5. State whether records are live, stale, have no live feed, or are scheduled; include the returned timestamp.
6. Cite MobiData BW / NVBW, the data providers, and the returned licence.
7. Explain that traffic-sign data is not legally binding, coverage varies, and supplementary signs are missing.
8. Answer in the user's language, German or English.
9. When the client supports artifacts, render returned GeoJSON on a simple Leaflet map.