# MobiData BW MCP: Tool Reference

This reference covers all 19 tools. Parameter names, types and defaults are generated from the running server; regenerate with `uv run python scripts/generate_tools_doc.py`.

## Result format

Every data tool returns the same envelope:

| Field | Meaning |
|---|---|
| `query` | The resolved request, including the geocoded place for location searches |
| `count` | Number of items in this response |
| `items` | The results |
| `truncated` and `next_cursor` | Set when more results exist; `next_cursor` pages `find_parking` |
| `source` | Dataset, endpoint, licence and attribution text |
| `data_timestamp` | Newest data time where the source provides one |
| `warnings` | Freshness, coverage and licence caveats; always show these to users |

Fields with no value are omitted from items. Live items carry `is_live`, `age_minutes` and `updated_at`; data older than 30 minutes is treated as not live.

## Overview

| Tool | Category | What it does |
|---|---|---|
| [`search_datasets`](#search_datasets) | Discovery | Search the catalogue by topic. Use group to list a whole category, e.g. parkraum for all parking datasets; an empty query matches everything. |
| [`get_dataset`](#get_dataset) | Discovery | Get authoritative metadata and current resource URLs for one catalogue dataset. |
| [`list_layers`](#list_layers) | Discovery | List current MobiData BW WFS layers and known geometry attributes; cached for 24 hours. |
| [`query_layer`](#query_layer) | Generic | Query any current WFS layer by location or bbox. CQL supports simple comparisons only. |
| [`find_parking`](#find_parking) | Parking | Find the nearest parking with live capacity. Use next_cursor for further results. |
| [`find_accessible_parking`](#find_accessible_parking) | Accessibility | Find disabled parking from live ParkAPI records and BFRK accessibility surveys. |
| [`stop_accessibility`](#stop_accessibility) | Accessibility | Summarize surveyed accessibility for a named or nearby Baden-Württemberg stop. |
| [`find_charging`](#find_charging) | E-mobility | Find nearby charge locations, filtering by maximum power and live connector availability. |
| [`find_sharing`](#find_sharing) | Sharing | Find live sharing stations and free-floating vehicles, counts, and range. |
| [`find_transit`](#find_transit) | Public transport | Find scheduled-transit stops and stations nearby; this is not realtime service data. |
| [`get_departures`](#get_departures) | Public transport | One merged station-complex timetable, inclusive time window, up to 30 departures. |
| [`get_live_departures`](#get_live_departures) | Public transport | Get TRIAS departures with scheduled/predicted times, delays and cancellations. |
| [`plan_transit_journey`](#plan_transit_journey) | Public transport | Plan A-to-B public transport journeys through EFA-BW TRIAS, including arrive-by searches. |
| [`get_roadworks`](#get_roadworks) | Traffic events | Find roadworks active on a date or during any day in a date range. |
| [`find_traffic_signs`](#find_traffic_signs) | Transport networks | Find traffic signs by radius or bbox. Results are advisory and omit supplementary signs. |
| [`find_traffic_messages`](#find_traffic_messages) | Traffic events | Find current traffic messages (accidents, congestion, closures, obstructions, works). |
| [`check_route`](#check_route) | Route check | Check a route for roadworks, traffic messages, and advisory truck signs. |
| [`data_health`](#data_health) | Quality | Audit fresh, stale, and no-live-feed records; parking defaults to off-street. |
| [`about`](#about) | Meta | Describe this server, its source systems, licences, and important caveats. |

## search_datasets

Search the catalogue by topic. Use group to list a whole category, e.g. parkraum for all parking datasets; an empty query matches everything.

Example question: Show all parking datasets (group parkraum).

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `query` | string | optional | Search words. Empty or blank matches everything. |
| `limit` | integer | default `10` | Maximum datasets returned (1 to 200). |
| `group` | string | optional | One of the 10 website categories, for example parkraum or oeffentlicher-personenverkehr. |

**Returns:** title, slug, description (160 characters), licence, licence_missing, last_modified, formats. query.total_matches gives the full match count.

**Source:** CKAN catalogue (mobidata-bw.de/api/3/action/). **Licence:** Varies per dataset (reported in each item).

**Caveats:**
- Free-text search ranks loosely; use group to list a whole category exactly.
- Results are cached for 1 hour.

## get_dataset

Get authoritative metadata and current resource URLs for one catalogue dataset.

Example question: Give me the licence and download links of the dataset bikesh.

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `dataset_id` | string | required | Dataset slug, for example bikesh. |

**Returns:** title, slug, full description, licence, last_modified and the list of resources with their current download URLs.

**Source:** CKAN catalogue (mobidata-bw.de/api/3/action/). **Licence:** Varies per dataset.

**Caveats:**
- Use the slug from search_datasets as dataset_id.

## list_layers

List current MobiData BW WFS layers and known geometry attributes; cached for 24 hours.

Example question: Which map layers can you query?

No parameters.

**Returns:** name, title and geometry_attribute of each of the 13 current WFS layers.

**Source:** GeoServer WFS (api.mobidata-bw.de/geoserver). **Licence:** See individual dataset metadata.

**Caveats:**
- Cached for 24 hours.

## query_layer

Query any current WFS layer by location or bbox. CQL supports simple comparisons only.

Example question: Show bicycle service points within 2 km of Freiburg Hauptbahnhof.

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `layer` | string | required | Full layer name, for example MobiData-BW:bicycle_service_points. |
| `location` | string or object | optional | Place name or {lat, lon}. Give location or bbox. |
| `bbox` | object | optional | {min_lat, min_lon, max_lat, max_lon}. Alternative to location. |
| `radius_m` | integer | default `1000` | Search radius around location. |
| `filter` | string | optional | Optional simple CQL comparison, for example name = 'x'. |
| `limit` | integer | default `20` | Maximum features returned. |

**Returns:** properties (all layer attributes), geometry, lat, lon and distance_m when a location is given. Coordinates are always WGS84.

**Source:** GeoServer WFS (api.mobidata-bw.de/geoserver). **Licence:** See individual dataset metadata.

**Caveats:**
- Use layer names from list_layers.
- filter accepts simple comparisons only; semicolons, comments and || are rejected.
- Long line features (for example the cycle network) are matched by a representative point, so use a radius of 1,000 m or more for them.

## find_parking

Find the nearest parking with live capacity. Use next_cursor for further results.

Example question: Where can I park near Heilbronn Hauptbahnhof?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | required | Place name or {lat, lon}. |
| `radius_m` | integer | default `1000` | Search radius. |
| `purpose` | one of CAR, BIKE, MOTORCYCLE, ITEM | default `CAR` | CAR, BIKE (stands and lockers), MOTORCYCLE or ITEM (bike boxes). |
| `only_free` | boolean | default `False` | Only sites with free spaces right now. |
| `truck` | boolean | default `False` | Only sites with truck capacity; uses truck capacity and free spaces. |
| `limit` | integer | default `20` | Page size. |
| `cursor` | integer | optional | Offset from the previous result's next_cursor. |

**Returns:** id, name, type, address, capacity, free_now, max_height_m, lat, lon, distance_m, is_live, age_minutes, updated_at. Sorted nearest first.

**Source:** ParkAPI v3 (api.mobidata-bw.de/park-api), 71 upstream sources. **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Fetches every site in the radius, sorts by distance, then pages with next_cursor.
- In very dense areas (over about 1,000 sites) the radius is narrowed and a warning says so.
- On-street records are static; they have no live occupancy.
- Motorcycle parking is published by very few sources.

## find_accessible_parking

Find disabled parking from live ParkAPI records and BFRK accessibility surveys.

Example question: Are there disabled parking spaces near Stuttgart Hauptbahnhof?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | required | Place name or {lat, lon}. |
| `radius_m` | integer | default `1000` | Search radius. |
| `limit` | integer | default `20` | Maximum items returned. |

**Returns:** id, name, capacity_disabled, lat, lon, distance_m, source_label, survey_year, survey_date, network, type; live fields for ParkAPI sites.

**Source:** ParkAPI v3 plus BFRK accessibility surveys (NVBW CSV files). **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- BFRK surveys were taken in different years and may be outdated.
- BFRK coordinates are deliberately offset by about 1.5 to 4 m.

## stop_accessibility

Summarize surveyed accessibility for a named or nearby Baden-Württemberg stop.

Example question: Is Heidelberg Hauptbahnhof step-free?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `stop_or_location` | string or object | required | Stop name, or a place or {lat, lon} to find the nearest stop. |

**Returns:** name, municipality, network, step_free and step_free_basis, platform_access, platform_or_curb_heights_cm, stairs_count, ramps, elevators, tactile_guidance, wheelchair_toilets, disabled_parking_spaces, bottlenecks, photo_links, survey_years.

**Source:** BFRK accessibility surveys (CKAN datasets for SPNV stations and OEPNV stops). **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Surveyed infrastructure, not live status; elevator records are not live outages.
- Surveys may be outdated.

## find_charging

Find nearby charge locations, filtering by maximum power and live connector availability.

Example question: Find chargers within 1 km of Mannheim Hauptbahnhof.

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | required | Place name or {lat, lon}. |
| `radius_m` | integer | default `2000` | Search radius. |
| `min_power_kw` | number | default `0` | Only locations whose maximum power is at least this value. |
| `only_available` | boolean | default `False` | Only locations with at least one free connector. |

**Returns:** id, name, operator, address, city, max_power_kw, available, total, charging, out_of_order, lat, lon, distance_m, is_live, age_minutes, updated_at.

**Source:** GeoServer WFS (api.mobidata-bw.de/geoserver), layer charge_points. **Licence:** See individual dataset metadata.

**Caveats:**
- Many locations have no current status; the warning counts them.
- Returns every location in the radius (up to 1,000); there is no limit setting.

## find_sharing

Find live sharing stations and free-floating vehicles, counts, and range.

Example question: Are there e-scooters near Stuttgart Hauptbahnhof?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | required | Place name or {lat, lon}. |
| `radius_m` | integer | default `500` | Search radius. |
| `kind` | string | default `any` | any, bicycle, car, scooter, cargo_bicycle or moped. |

**Returns:** item_type (station or vehicle), operator, name, kind, propulsion_type, available counts, virtual_station_inventory, count_semantics, current_range_m, max_range_m, battery_pct, rental_link, lat, lon, distance_m, is_live, updated_at.

**Source:** GeoServer WFS (api.mobidata-bw.de/geoserver), layers sharing_stations and sharing_vehicles (GBFS feeds). **Licence:** See individual dataset metadata.

**Caveats:**
- Counts at virtual stations are inventory, not physically parked vehicles.
- Free-floating vehicles are reported individually.

## find_transit

Find scheduled-transit stops and stations nearby; this is not realtime service data.

Example question: Which stops are near Konstanz Bahnhof?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | required | Place name or {lat, lon}. |
| `radius_m` | integer | default `500` | Search radius. |

**Returns:** id, name, item_type (stop or station), lat, lon, distance_m.

**Source:** GeoServer WFS (api.mobidata-bw.de/geoserver), layers transit_stops and transit_stations_with_served_routes. **Licence:** CC BY 4.0.

**Caveats:**
- Scheduled timetable data only; no real-time information.

## get_departures

One merged station-complex timetable, inclusive time window, up to 30 departures.

Example question: When does the next train leave Heidelberg Hauptbahnhof on Monday at 08:00?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `stop_or_station_id` | string | required | Stop or station id from find_transit, for example de:08416:10508:0:4. |
| `date` | string | optional | Service date (ISO). Defaults to today. |
| `from_time` | string | optional | Legacy start time (ISO datetime); time_from takes precedence. |
| `limit` | integer | default `30` | Maximum departures. |
| `time_from` | string | optional | Inclusive start time (ISO datetime). |
| `time_to` | string | optional | Inclusive end time (ISO datetime). |
| `platform_only` | boolean | default `False` | Restrict to the specified platform instead of the station complex. |

**Returns:** route, headsign, departure, scheduled_time, stop_id, stop_name, station_name, wheelchair_accessible.

**Source:** GTFS API (api.mobidata-bw.de/gtfs, arrivals_departures). **Licence:** CC BY 4.0.

**Caveats:**
- Scheduled times, not real time.
- Dates close to today may not be published yet.
- The timetable database can time out; retrying usually works.

## get_live_departures

Get TRIAS departures with scheduled/predicted times, delays and cancellations.

Example question: Are departures from Heilbronn Hbf delayed right now?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `stop_or_location` | string or object | required | Station/place, explicit TRIAS stop ID or {lat, lon}. |
| `time_from` | string | optional | Window start; defaults to now. Naive times mean Europe/Berlin. |
| `time_to` | string | optional | Window end; defaults to +90 minutes. Maximum window: 6 hours. |
| `limit` | integer | default `10` | Maximum departures (1–30). |
| `fallback_to_schedule` | boolean | default `True` | Use explicitly labelled GTFS scheduled data on TRIAS failure. |
| `cursor` | integer | default `0` | Result offset; use the previous response's next_cursor (default 0). |

**Returns:** route, headsign, stop_name, scheduled_time, estimated_time, time, delay_minutes, platform, scheduled_platform, platform_changed, cancelled, is_live. Paging metadata includes next_cursor, available_count and window_complete. The source changes to GTFS when fallback is used.

**Source:** NVBW EFA-BW TRIAS 1.2; optional scheduled GTFS fallback. **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Requires TRIAS_URL and TRIAS_REQUESTOR_REF on the MCP server; requests use XML over HTTPS.
- Source requests page through the time window; pass next_cursor as cursor with the same window to retrieve subsequent result pages.
- Missing predictions do not mean on time. Operator coverage varies.
- Coordinate queries discover up to three stop groups within 500 m; coverage may be incomplete.
- Identical successful responses are cached for 30 seconds; station IDs for 24 hours. GTFS fallback is scheduled only.

## plan_transit_journey

Plan A-to-B public transport journeys through EFA-BW TRIAS, including arrive-by searches.

Example question: Find a wheelchair-suitable journey from Stuttgart Hbf to Heilbronn Hbf, arriving before 09:00 tomorrow.

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `origin` | string or object | required | Starting place, stop ID or {lat, lon}. |
| `destination` | string or object | required | Destination place, stop ID or {lat, lon}. |
| `departure_time` | string | optional | Depart-at timestamp; defaults to now unless arrival_time is given. |
| `arrival_time` | string | optional | Arrive-by timestamp; cannot be combined with departure_time. |
| `wheelchair` | boolean | default `False` | Request no steps/stairs/escalators and level boarding. |
| `max_transfers` | integer | optional | Maximum transfers (0–5); zero is filtered locally. |
| `limit` | integer | default `3` | Maximum journey alternatives (1–5). |

**Returns:** Journey departure, arrival, duration, transfers and all legs. Timed legs carry board/alight stops, scheduled and estimated times, platforms and cancellation. Wheelchair preferences are reported separately from verified accessibility.

**Source:** NVBW EFA-BW TRIAS 1.2 TripRequest. **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Requires configured TRIAS access. No route is invented if the source fails.
- Arrival and departure constraints are alternatives. Naive times mean Europe/Berlin.
- Accessibility preferences do not guarantee working lifts or an accessible journey.
- Coordinate journeys request up to 15 minutes of walking access.
- Fares, booking and automatic journey monitoring are not implemented.

## get_roadworks

Find roadworks active on a date or during any day in a date range.

Example question: Are there roadworks in Ulm today?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | optional | Place name or {lat, lon}. Give location or bbox. |
| `bbox` | object | optional | {min_lat, min_lon, max_lat, max_lon}. |
| `radius_m` | integer | default `5000` | Search radius around location. |
| `active_on` | string | optional | A single date (ISO). |
| `active_from` | string | optional | Start of a date range. |
| `active_to` | string | optional | End of a date range. |

**Returns:** id, street, type, subtype, description, direction, start, end, lat, lon, distance_m, geometry_type.

**Source:** Roadworks GeoJSON (api.mobidata-bw.de/datasets/traffic/roadworks). **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Defaults to today when no date is given.
- active_on cannot be combined with active_from or active_to.
- Cached for 15 minutes.

## find_traffic_signs

Find traffic signs by radius or bbox. Results are advisory and omit supplementary signs.

Example question: Are there truck restrictions near Heilbronn?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | optional | Place name or {lat, lon}. Give location or bbox. |
| `bbox` | object | optional | {min_lat, min_lon, max_lat, max_lon}. |
| `radius_m` | integer | default `500` | Search radius around location. |
| `sign_codes` | list of string | optional | Only these sign numbers, for example ["265"]. |
| `truck_relevant_only` | boolean | default `False` | Only the truck-relevant codes listed above. |

**Returns:** sign_code, raw_sign_code, meaning, municipality, lat, lon, distance_m, last_updated.

**Source:** Traffic signs GeoJSON (mobidata-bw.de/daten/portal/VZ-Daten). **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Advisory only, not legally binding.
- Supplementary signs (for example Lieferverkehr frei) are not included.
- Municipal coverage varies. Truck-relevant codes: 253, 262, 263, 264, 265, 266, 277.

## find_traffic_messages

Find current traffic messages (accidents, congestion, closures, obstructions, works).

Example question: Any accidents or road closures near Stuttgart right now?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `location` | string or object | required | Place name or {lat, lon}. |
| `radius_m` | integer | default `5000` | Search radius. |
| `limit` | integer | default `20` | Maximum messages. |

**Returns:** id, category, type, severity, description (German), location_description, start, end, lat, lon, distance_m. data_timestamp is the feed publication time.

**Source:** DATEX II traffic messages (api.mobidata-bw.de/datasets/traffic/incidents). **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- State-wide snapshot that may lag real conditions; cached for 5 minutes.
- Severity is high for accidents and for texts mentioning a closure.
- Records with the same text and place are merged.

## check_route

Check a route for roadworks, traffic messages, and advisory truck signs.

Example question: I'm driving a 40 t truck, 4 m high, from Karlsruhe via Pforzheim to Stuttgart. Any restrictions?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `route` | object or list of items | required | GeoJSON LineString, or a list of {lat, lon} waypoints in travel order. |
| `buffer_m` | integer | default `30` | Distance on each side of the route (1 to 1,000 m). |
| `date` | string | optional | Travel date (ISO). Defaults to today. |
| `vehicle` | object | optional | {weight_t, height_m}; used to flag weight and height limits that are exceeded. |

**Returns:** Findings ordered by km_from_start: kind (roadwork, traffic_message or traffic_sign), route_relation (on_route or near_route), distance_to_route_m, severity, description, plus sign_code, limit and vehicle_exceeds_limit for signs. The first warning is a count summary.

**Source:** Roadworks, DATEX II traffic messages and traffic signs; OpenRouteService HGV routing when configured. **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- A list of points is routed with OpenRouteService when a key is set; otherwise straight lines approximate the route and the buffer is at least 500 m.
- If the traffic message feed is down, roadworks and signs are still returned and a warning says incidents are missing.
- Sign results are advisory.

## data_health

Audit fresh, stale, and no-live-feed records; parking defaults to off-street.

Example question: How fresh is the parking data in Heilbronn?

| Parameter | Type | Required or default | Description |
|---|---|---|---|
| `region` | string | optional | City or region name; omit for all of Baden-Württemberg. |
| `dataset` | string | default `all` | parking, charging, sharing or all. |
| `parking_scope` | string | default `off_street` | off_street, on_street or all. |

**Returns:** Per dataset: groups (live_and_fresh, live_capable_but_stale, no_live_feed), live_percent and its basis, median_age_min, max_age_min, oldest_site, stale_sites, top_regions, area_used, status.

**Source:** ParkAPI v3 and GeoServer WFS (charging, sharing). **Licence:** Datenlizenz Deutschland - Namensnennung 2.0.

**Caveats:**
- Fresh means updated within 30 minutes.
- Parking defaults to off-street sites; on-street records have no live feed.

## about

Describe this server, its source systems, licences, and important caveats.

Example question: What data sources do you use and under which licences?

No parameters.

**Returns:** name, version, description, sources, licences, caveats, contact. Also available as the MCP resource mobidata://about.

**Source:** This server. **Licence:** PolyForm Noncommercial 1.0.0 (current project); separate commercial licence available.

**Caveats:**
- This independent project is not affiliated with or endorsed by NVBW.
