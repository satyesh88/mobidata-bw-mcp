# MobiData BW MCP – Data Coverage

Snapshot: 2026-10-17, from the live CKAN catalogue (`https://mobidata-bw.de/api/3/action/`), live ParkAPI and live GeoServer WFS.

Implementation coverage updated 2026-10-22 for the optional TRIAS tools. Catalogue
and feed inventory counts below retain the dated snapshot above.

## Status legend

| Status | Meaning |
|---|---|
| **Covered** | A purpose-built tool consumes this dataset (or the feed that is this dataset). |
| **Generic** | Reachable only through the generic `query_layer` (WFS) or `search_datasets` / `get_dataset` (metadata). No tailored tool. |
| **Indirect** | The same real-world data arrives through a different or aggregated source. This exact dataset is not read. |
| **Not covered** | Not read by any tool. `search_datasets` / `get_dataset` still return its metadata and download URLs. |

## Why a dataset is not covered (reason codes)

The server answers location-based questions with live or fresh data and a source, licence and freshness stamp. A dataset is left out when it does not fit that purpose, or when it cannot be served reliably. Every non-covered row in section 3 carries one or more of these codes.

| Code | Reason |
|---|---|
| **R1** | Statistics, survey or analysis product (annual counts, studies, yearbooks, demand maps). It does not answer "what is near me / what is happening now", and its freshness is months to years. |
| **R2** | Bulk file with no API (XLSX, PDF, shapefile, ZIP, CSV). Serving it needs a download, parsing and storage pipeline per dataset, with no live data. |
| **R3** | Redundant. A subset or bundle of a feed that is already served; adding it would risk inconsistent answers. |
| **R4** | Single city, district or pilot. Low reach for the integration and maintenance cost. |
| **R5** | Access needs registration. TRIAS requires a personal requestor key from NVBW (request by email to mobidata-bw@nvbw.de). |
| **R6** | Data too thin to answer questions. Verified 2026-10-17: `mobilstationen-bw` has 1,972 polygons with no attributes; `bruecken-bw` has 9,825 points with only name, road and station (no clearance or load limit). |
| **R7** | Broken upstream resource. Verified 2026-10-17: the download URL returns HTTP 404. |
| **R8** | Portal or web-app link only; no machine-readable resource to fetch. |
| **R9** | The same data is already served through another channel. |
| **R10** | Valid candidate, deliberately deferred. Small or niche value, can be added later as a focused tool. |

## 1. Category to code map

All 10 website categories exist as CKAN groups. 8 of 10 have at least one dedicated tool. "Other" and "Traffic counting data" have none.

| # | Category (CKAN group) | Datasets | MCP tools | Code files |
|---|---|---|---|---|
| 1 | Accessibility (`barrierefreiheit`) | 4 | `stop_accessibility`, `find_accessible_parking` | [tools/accessibility.py](src/mobidata_bw_mcp/tools/accessibility.py), [clients/bfrk.py](src/mobidata_bw_mcp/clients/bfrk.py), [clients/parkapi.py](src/mobidata_bw_mcp/clients/parkapi.py) |
| 2 | E-mobility (`e-mobilitaet`) | 3 | `find_charging`, `find_sharing` | [tools/charging.py](src/mobidata_bw_mcp/tools/charging.py), [tools/sharing.py](src/mobidata_bw_mcp/tools/sharing.py) |
| 3 | Foot and bike traffic (`fuss-und-radverkehr`) | 11 | `find_parking` (`purpose=BIKE`), `find_sharing`, `stop_accessibility`, `query_layer` | [tools/parking.py](src/mobidata_bw_mcp/tools/parking.py), [tools/sharing.py](src/mobidata_bw_mcp/tools/sharing.py), [tools/spatial.py](src/mobidata_bw_mcp/tools/spatial.py) |
| 4 | Parking space (`parkraum`) | 15 | `find_parking`, `find_accessible_parking`, `data_health` | [tools/parking.py](src/mobidata_bw_mcp/tools/parking.py), [tools/accessibility.py](src/mobidata_bw_mcp/tools/accessibility.py), [tools/health.py](src/mobidata_bw_mcp/tools/health.py), [clients/parkapi.py](src/mobidata_bw_mcp/clients/parkapi.py) |
| 5 | Sharing offers (`sharing-angebote`) | 8 | `find_sharing`, `data_health` | [tools/sharing.py](src/mobidata_bw_mcp/tools/sharing.py), [tools/health.py](src/mobidata_bw_mcp/tools/health.py) |
| 6 | Other (`sonstiges`) | 10 | none (metadata only) | [tools/discovery.py](src/mobidata_bw_mcp/tools/discovery.py) |
| 7 | Traffic events (`verkehrsereignisse`) | 2 | `get_roadworks`, `find_traffic_messages`, `check_route` | [tools/roadworks.py](src/mobidata_bw_mcp/tools/roadworks.py), [tools/traffic_messages.py](src/mobidata_bw_mcp/tools/traffic_messages.py), [tools/route_check.py](src/mobidata_bw_mcp/tools/route_check.py), [clients/static_files.py](src/mobidata_bw_mcp/clients/static_files.py), [clients/traffic_messages.py](src/mobidata_bw_mcp/clients/traffic_messages.py), [clients/routing.py](src/mobidata_bw_mcp/clients/routing.py) |
| 8 | Transport networks (`verkehrsnetze`) | 6 | `find_traffic_signs`, `check_route`, `query_layer` | [tools/signs.py](src/mobidata_bw_mcp/tools/signs.py), [tools/route_check.py](src/mobidata_bw_mcp/tools/route_check.py), [tools/spatial.py](src/mobidata_bw_mcp/tools/spatial.py) |
| 9 | Traffic counting data (`verkehrszaehldaten`) | 14 | none (metadata only) | [tools/discovery.py](src/mobidata_bw_mcp/tools/discovery.py) |
| 10 | Public transport (`oeffentlicher-personenverkehr`) | 24 | `find_transit`, `get_departures`, `get_live_departures`, `plan_transit_journey`, `stop_accessibility`, `query_layer` | [tools/transit.py](src/mobidata_bw_mcp/tools/transit.py), [clients/gtfs.py](src/mobidata_bw_mcp/clients/gtfs.py), [clients/wfs.py](src/mobidata_bw_mcp/clients/wfs.py) |

Cross-cutting files: [tools/discovery.py](src/mobidata_bw_mcp/tools/discovery.py) (`search_datasets`, `get_dataset`, `list_layers` for all 146 catalogue datasets), [tools/spatial.py](src/mobidata_bw_mcp/tools/spatial.py) (`query_layer` for any of the 13 WFS layers), [clients/ckan.py](src/mobidata_bw_mcp/clients/ckan.py), [clients/geocode.py](src/mobidata_bw_mcp/clients/geocode.py).

## 2. Upstream sources actually fetched

| Source | Used by | Config |
|---|---|---|
| ParkAPI v3 (71 upstream sources, 32,025 records) | `find_parking`, `find_accessible_parking`, `data_health` | `parkapi_url` |
| GeoServer WFS `MobiData-BW:charge_points` | `find_charging`, `data_health` | `wfs_url` |
| GeoServer WFS `sharing_stations`, `sharing_vehicles` | `find_sharing`, `data_health` | `wfs_url` |
| GeoServer WFS `transit_stops`, `transit_stations_with_served_routes` | `find_transit` | `wfs_url` |
| GTFS arrivals/departures API | `get_departures` (scheduled only) | `gtfs_url` |
| NVBW EFA-BW TRIAS 1.2 | `get_live_departures`, `plan_transit_journey` (configured access) | `TRIAS_URL`, `TRIAS_REQUESTOR_REF` |
| `roadworks_geojson.json` | `get_roadworks`, `check_route` | `roadworks_url` |
| `incidents_lmsbw.datex2.xml` (DATEX II traffic messages, about 35 situations, refreshed every few minutes) | `find_traffic_messages`, `check_route` | `traffic_messages_url` |
| `VZ-Daten/signs.geojson` | `find_traffic_signs`, `check_route` | `signs_url` |
| BFRK CSV files (NVBW, resolved through CKAN) | `stop_accessibility`, `find_accessible_parking` | `ckan_url` |
| OpenRouteService HGV directions | `check_route` | [clients/routing.py](src/mobidata_bw_mcp/clients/routing.py) |
| Nominatim | location resolution | `nominatim_url` |
| CKAN `package_search` / `package_show` | `search_datasets`, `get_dataset`, BFRK resource lookup | `ckan_url` |

The remaining 8 of 13 WFS layers (`roadworks`, `park-api_car`, `park-api_car_lines`, `park-api_car_polygons`, `park-api_bicycle`, `radvis_cycle_network`, `bicycle_service_points`, `transit_shapes_with_routes`) are only reachable through `query_layer`. The first five duplicate data already served by dedicated tools. Spot-tested on 2026-10-17: `radvis_cycle_network`, `bicycle_service_points`, `transit_shapes_with_routes`, `park-api_bicycle` all return features.

## 3. Dataset-level coverage

### 3.1 Accessibility (4)

| Dataset | Status | How / why |
|---|---|---|
| `bfrk-barrierefreiheit-an-bw-bahnhoefen` (SPNV stations) | Covered | `stop_accessibility`, `find_accessible_parking` read the BFRK CSVs |
| `bfrk-barrierefreiheit-an-bw-haltestellen` (ÖPNV stops) | Covered | `stop_accessibility` |
| `daten-barrierefreiheit` (BFRK API) | Indirect (R9) | Same BFRK survey data is read from the CSV exports instead of the API, which avoids a second integration for identical content |
| `fgue-bw` (pedestrian crossings) | Not covered (R10) | Small GeoJSON of crossing points; useful for step-free routing but too thin for a standalone tool |

### 3.2 E-mobility (3)

| Dataset | Status | How / why |
|---|---|---|
| `e-ladesaulen` | Covered | `find_charging` (WFS `charge_points`) |
| `e-kleinkraftrad-sharing` | Covered | `find_sharing` (`kind=moped`) |
| `fahrrad-e-ladesaulen` (Reutlingen) | Not covered (R7, R4) | Download URL returns HTTP 404, and it is a single-city dataset |

### 3.3 Foot and bike traffic (11)

| Dataset | Status | How / why |
|---|---|---|
| `gebundelte-fahrradabstellanlagen-baden-wurttemberg` | Covered | `find_parking` with `purpose=BIKE` (ParkAPI) |
| `bikesh` | Covered | `find_sharing` (`kind=bicycle`) |
| `cargobike` | Covered | `find_sharing` (`kind=cargo_bicycle`) |
| `lastenrad-sharing-lastenkarle` | Covered | Feed `lastenkarle` present in sharing layers (18 stations) |
| `bfrk-barrierefreiheit-an-bw-bahnhoefen` | Covered | `stop_accessibility` |
| `radnetz-bw` | Generic | Cycle-network geometry via `query_layer` on `radvis_cycle_network`. A dedicated tool would need routing logic, not a lookup |
| `radservicepunkte` | Generic | Repair/pump points via `query_layer` on `bicycle_service_points`; small point set that does not justify its own tool |
| `eco-counter-fahrradzahler` | Not covered (R1, R10) | Bike counter time series (CSV/API). A statistics question, not a "where" question; candidate for a later tool |
| `besserradfahren-swr-umfrage` | Not covered (R1, R2) | One-off SWR survey as XLSX |
| `fgue-bw` | Not covered (R10) | See 3.1 |
| `fahrradparken-kapazitaet` (VRN) | Not covered (R4) | Regional ArcGIS layer for the VRN area only; no VRN bike source exists in ParkAPI |

### 3.4 Parking space (15)

| Dataset | Status | How / why |
|---|---|---|
| `gebuendelte-parkdaten-bw` | Covered | `find_parking` (ParkAPI, car) |
| `gebundelte-daten-strassen-parkplatze-bw` | Covered | `find_parking`; 22,169 on-street records, all static (not live) |
| `gebundelte-fahrradabstellanlagen-baden-wurttemberg` | Covered | `find_parking` with `purpose=BIKE` |
| `bfrk-barrierefreiheit-an-bw-bahnhoefen` | Covered | BFRK `Parkplatz.csv` via `find_accessible_parking` |
| `bfrk-barrierefreiheit-an-bw-haltestellen` | Covered | Stop accessibility only; its parking is not read |
| `p-m-parkplatze-baden-wurttemberg` | Covered | ParkAPI sources `pum_bw`, `p_m_bw` |
| `parkdaten-freiburg` | Covered | ParkAPI sources `freiburg`, `freiburg_scanner` |
| `parkdaten-herrenberg` | Covered | ParkAPI sources `herrenberg`, `herrenberg_bike` |
| `parkleitsystem-konstanz` | Covered | ParkAPI source `konstanz` (+ `konstanz_bike`) |
| `on-street-parkplatze` (Heidelberg) | Indirect (R9) | Heidelberg on-street comes from ParkAPI source `heidelberg_easypark` (7,969 records), so the city is answered, but not from this city dataset |
| `motorradparkplatze-pforzheim` | Not covered (R7) | Download URL returns HTTP 404. ParkAPI `pforzheim` has car parks only; the only motorcycle source is `esslingen` (43 records) |
| `ruhender-verkehr-s-bad-cannstatt` | Not covered (R4) | Static GeoJSON for one Stuttgart district; no ParkAPI source |
| `parkleitsystem-der-stadt-basel` | Not covered (R4) | Swiss city outside Baden-Württemberg; the upstream endpoint returned HTTP 500 on test |
| `fahrradparken-kapazitaet` (VRN) | Not covered (R4) | See 3.3 |
| `verkehr` (Konstanz ESRI hub) | Not covered (R8) | Web-app and portal link only; the machine-readable Konstanz parking data is already served through ParkAPI |

### 3.5 Sharing offers (8)

All 8 are bundled GBFS feeds that reach us through the WFS sharing layers, so `find_sharing` covers them.

| Dataset | Status | How / why |
|---|---|---|
| `carsharing` | Covered | `find_sharing` (`kind=car`) |
| `bikesh` | Covered | `find_sharing` (`kind=bicycle`) |
| `cargobike` | Covered | `find_sharing` (`kind=cargo_bicycle`) |
| `escootch` | Covered | `find_sharing` (`kind=scooter`) |
| `e-kleinkraftrad-sharing` | Covered | `find_sharing` (`kind=moped`) |
| `stadtmobil-stuttgart-stationsdaten` | Covered | Feed `stadtmobil_stuttgart` (353 stations) |
| `swu2go-gbfs` | Covered | Feed `swu2go` (29 stations) |
| `lastenrad-sharing-lastenkarle` | Covered | Feed `lastenkarle` (18 stations) |

### 3.6 Other (10)

No category-specific tool. All 10 are Not covered; metadata and links remain available through `search_datasets` and `get_dataset`.

| Dataset | Status | Why |
|---|---|---|
| `posterumfrage-angebote-mobilitatsstation-eselsberg-2107` | Not covered (R1, R4) | One-off survey in Ulm (CSV) |
| `ferdinand-steinbeis-institut-pilotstudie-track4science` | Not covered (R1) | Research study data (CSV) |
| `motorradlarm-hotspots-daten` | Not covered (R1, R2) | Noise hotspot statistics as XLSX |
| `winterdienstsensor-neulingen-olbronn-durrn` | Not covered (R4) | Two-site sensor pilot; the resource link is not a directly fetchable HTTP URL |
| `statistisches-jahrbuch-verkehr` | Not covered (R1, R2) | Heidelberg statistics yearbook chapter (PDF/XLSX) |
| `motorradparkplatze-pforzheim` | Not covered (R7) | Download URL returns HTTP 404 (see 3.4) |
| `mobilstationen-bw` | Not covered (R6) | 1,972 polygons with no attributes: no name, no services, no operator. It could only answer "there is a hub polygon here"; sharing stations already give the actual services |
| `gps-daten-wochenmarkt-lieferdienst` | Not covered (R1, R4) | GPS tracks of one delivery pilot in Ulm |
| `gebundelte-taxistellplatze-baden-wurttemberg` | Not covered (R7) | Download URL returns HTTP 404 |
| `bruecken-bw` | Not covered (R6) | 9,825 bridge points with name, road and station only. There is no clearance or load limit, so it cannot support truck route checks |

### 3.7 Traffic events (2)

| Dataset | Status | How / why |
|---|---|---|
| `baustelleninformationen-baden-wurttemberg` | Covered | `get_roadworks`, `check_route` (GeoJSON) |
| `meldung` (traffic messages, DATEX II) | Covered | `find_traffic_messages` and `check_route`. Accidents, congestion, closures and obstructions from the DATEX II feed; records with the same text and place are merged |

### 3.8 Transport networks (6)

| Dataset | Status | How / why |
|---|---|---|
| `verkehrszeichen-baden-wurttemberg` | Covered | `find_traffic_signs`, `check_route` (advisory) |
| `radnetz-bw` | Generic | See 3.3 |
| `strassennetz-netzknoten-baden-wuerttemberg` | Not covered (R2) | Reference network and junction tables (CSV/XLS/ZIP); no live data and no question it answers directly |
| `bedarfsumleitungen-baden-wurttemberg` | Not covered (R2, R10) | Planned diversion routes as XLSX. Relevant to closures, but it needs the network geometry above to be usable |
| `vz-freiburg` | Not covered (R4) | Freiburg-only signs WFS; statewide signs are already covered |
| `fgue-bw` | Not covered (R10) | See 3.1 |

### 3.9 Traffic counting data (14)

No tool. All 14 are Not covered. These are traffic and passenger statistics: historic, periodic and mostly report files, so they do not fit a live, place-based assistant.

| Dataset | Status | Why |
|---|---|---|
| `eco-counter-fahrradzahler` | Not covered (R1, R10) | Bike counter time series; the only one here with an API, so the best later candidate |
| `stundenwerte_dauerzaehlstellen` | Not covered (R1, R2) | Hourly values of permanent counters as bulk CSV (ZIP) |
| `ergebnisse_ganglinien_dauerzaehlstellen` | Not covered (R1, R2) | Result reports and curves (PDF/XLSX ZIP) |
| `endergebnisse_strassenverkehrszaehlung` | Not covered (R1, R2) | Final census results (PDF/XLSX ZIP) |
| `bundesweite_strassenverkehrszaehlung` | Not covered (R1, R2) | National census reports (PDF) |
| `verkehrsentwicklungen_jahresvergleiche_strassenverkehr` | Not covered (R1, R2) | Year-on-year comparison report (PDF ZIP) |
| `karte_strassenverkehrszaehlung` | Not covered (R1) | Census map visualisation and CSV |
| `nachfragekarte-spnv-bw` | Not covered (R1) | Rail demand analysis map (GeoJSON) |
| `automatische-fahrgast-zahldaten-baden-wurttemberg` | Not covered (R1, R2) | Passenger counts on regional rail (CSV ZIP) |
| `zaehldaten-gemeinde-berg` | Not covered (R1, R2, R4) | One municipality, XLSX |
| `zaehldaten-stadt-weingarten` | Not covered (R1, R2, R4) | One municipality, XLSX |
| `zaehldaten-gemeinde-baienfurt` | Not covered (R1, R2, R4) | One municipality, XLSX |
| `zaehldaten-gemeinde-baindt` | Not covered (R1, R2, R4) | One municipality, XLSX |
| `zaehldaten-ravensburg` | Not covered (R1, R2, R4) | One municipality, XLSX |

### 3.10 Public transport (24)

| Dataset | Status | How / why |
|---|---|---|
| `soll-fahrplandaten-baden-wurttemberg` (no line shapes) | Covered | `find_transit` (WFS stops/stations), `get_departures` (GTFS API) |
| `bfrk-barrierefreiheit-an-bw-bahnhoefen` | Covered | `stop_accessibility` |
| `bfrk-barrierefreiheit-an-bw-haltestellen` | Covered | `stop_accessibility` |
| `soll-fahrplandaten-baden-wurttemberg-mit-linienverlauf` | Generic | Line shapes via `query_layer` on `transit_shapes_with_routes`; shapes are map geometry, not an answer to a rider question |
| `haltestellen-baden-wuerttemberg` | Indirect (R9) | Equivalent stop data comes from the GTFS-derived WFS layers |
| `soll-fahrplandaten-vvs` | Indirect (R3) | Overlaps the statewide GTFS; per-operator inclusion not verified |
| `soll-fahrplandaten-verkehrsverbunde-bw-einzeln-ohne-linienverlauf` | Indirect (R3) | Per-network subset of the statewide GTFS |
| `soll-fahrplandaten-verkehrsverbunde-bw-einzeln-mit-linienverlauf` | Indirect (R3) | Per-network subset of the statewide GTFS |
| `soll-fahrplandaten-s-und-u-bahnen-bw-ohne-linienverlauf` | Indirect (R3) | Rail subset of the statewide GTFS |
| `soll-fahrplandaten-s-und-u-bahnen-bw-mit-linienverlauf` | Indirect (R3) | Rail subset of the statewide GTFS |
| `opnv-fahrplandaten-der-swu` | Indirect (R3) | Ulm operator feed; overlaps the statewide GTFS, not verified |
| `gebundelte-soll-fahrplandaten-fur-baden-wurttemberg-rheinland-pfalz-und-saarland-ohne-linienverlauf` | Indirect (R3) | Wider bundle; only the BW part is needed and served |
| `gebundelte-fahrplandaten-fur-baden-wurttemberg-rheinland-pfalz-und-saarland-mit-linienverlauf` | Indirect (R3) | Wider bundle; only the BW part is needed and served |
| `daten-barrierefreiheit` | Indirect (R9) | BFRK CSV used instead of the API |
| `trias` (real-time timetable) | Covered | `get_live_departures` and `plan_transit_journey`; requires configured requestor access. Predictions depend on operator coverage; GTFS fallback is scheduled only |
| `mitfahren` (Amarillo, GTFS-RT) | Not covered (R10) | Ride-matching offers rather than a stop or timetable lookup; a candidate for a later tool |
| `opnv-guteklassen` | Not covered (R1, R2) | Service-quality isochrones as shapefile; an analysis product |
| `nachfragekarte-spnv-bw` | Not covered (R1) | Rail demand analysis map (GeoJSON) |
| `zugkm-pkm-bw` | Not covered (R1, R2) | Annual train and passenger-kilometre statistics (XLSX) |
| `automatische-fahrgast-zahldaten-baden-wurttemberg` | Not covered (R1, R2) | Passenger count statistics (CSV ZIP) |
| `stops-20220624-geoexport` (VRN stops) | Not covered (R2, R4) | VRN-area stops as shapefile, dated 2022; statewide stops are already served |
| `linienverlauf-vrn` | Not covered (R2, R4) | VRN-area line shapes as shapefile |
| `gebundelte-taxistellplatze-baden-wurttemberg` | Not covered (R7) | Download URL returns HTTP 404 |
| `verkehr` (Konstanz) | Not covered (R8) | Portal and web-app link only |

## 4. Summary for the presentation

Counts are group memberships (97). A dataset in two groups is counted twice. 76 unique datasets sit in a group; the whole catalogue has 146.

| Category | Total | Covered | Generic | Indirect | Not covered |
|---|---:|---:|---:|---:|---:|
| Accessibility | 4 | 2 | 0 | 1 | 1 |
| E-mobility | 3 | 2 | 0 | 0 | 1 |
| Foot and bike traffic | 11 | 5 | 2 | 0 | 4 |
| Parking space | 15 | 9 | 0 | 1 | 5 |
| Sharing offers | 8 | 8 | 0 | 0 | 0 |
| Other | 10 | 0 | 0 | 0 | 10 |
| Traffic events | 2 | 2 | 0 | 0 | 0 |
| Transport networks | 6 | 1 | 1 | 0 | 4 |
| Traffic counting data | 14 | 0 | 0 | 0 | 14 |
| Public transport | 24 | 4 | 1 | 10 | 9 |
| **Total** | **97** | **33** | **4** | **12** | **48** |

Reason frequency (counted from the rows above; a row can carry several codes):

| Code | Rows | Applies to |
|---|---:|---|
| R1 statistics, surveys, analysis | 25 | Not covered |
| R2 bulk files, no API | 21 | Not covered |
| R4 single city or pilot | 16 | Not covered |
| R10 deferred candidates | 7 | Not covered |
| R7 broken upstream URL (404) | 5 | Not covered |
| R6 data too thin | 2 | Not covered |
| R8 portal link only | 2 | Not covered |
| R3 redundant bundle | 8 | Indirect |
| R9 same data via another channel | 4 | Indirect |

Strongest coverage is for live, location-based questions (parking, sharing, charging, roadworks, signs, transit, accessibility). Statistical, survey, counting and network-planning datasets are not covered.

## 5. Caveats to state openly

- One ParkAPI endpoint is not one dataset. It aggregates 71 upstream sources, so a parking "dataset" is covered through its source, not as a file.
- On-street parking is returned but static. None of the 22,169 on-street records has live occupancy.
- `find_parking` fetches every site in the radius, sorts by distance and only then applies the limit, so the nearest sites are never cut off. In very dense areas (more than about 1,000 sites) it narrows the radius and says so in a warning.
- `get_departures` remains scheduled data. TRIAS tools add live predictions and journey planning when configured; missing predictions do not confirm on-time running. Wheelchair routing preferences do not verify lift operation.
- Traffic messages are a state-wide DATEX II snapshot with German text. Records with the same text and place are merged. If the feed is down, `check_route` still returns roadworks and signs and says that incidents are missing.
- Motorcycle parking data exists for very few places, and `find_parking` says so when `purpose=MOTORCYCLE`.
- "Indirect" rows for GTFS bundles are inferred from overlap with the statewide feed, not verified operator by operator.
