---
name: mobidata-bw
description: Answer Baden-Württemberg mobility questions with the MobiData BW MCP server. Covers parking, EV charging, bike and car sharing, scheduled public transport, accessibility of stops and parking, roadworks, traffic messages, truck routes and the open-data catalogue. Use for any question about places, routes or mobility data in Baden-Württemberg, Germany.
---

# MobiData BW mobility answers

Requires the MobiData BW MCP server (17 tools). This skill only says when to use which tool and how to word the answer; see TOOLS.md in the repository for every parameter and result field.

## Core rules

- Use the tools before answering any factual mobility question. Never state facts, numbers, availability, times, routes or places that a tool did not return in the current turn.
- Pass a place name as the user wrote it, or explicit `lat` and `lon`. If a place is ambiguous, ask one short clarification.
- Always state the resolved place from `query.location` (not your own guess) as a first line, for example "Searched around: Stuttgart Hauptbahnhof".
- Always show freshness: live (with age in minutes), stale (older than 30 minutes), no live feed, scheduled, or surveyed (with the survey year). Quote the returned timestamp.
- Always pass on every item in `warnings`. If `truncated` is true, say that more results exist.
- If you state a count, it must equal the number of items you list.
- Times are Europe/Berlin, written HH:MM.
- A date without a year means its next upcoming occurrence from today's date. Pass dates to tools as ISO dates.
- Reply in the user's language, German or English.
- End every answer with the attribution line: Daten: MobiData BW® / NVBW und Datengeber. Name the licence when the user asks for it or the result flags it.
- If a tool fails or returns nothing, say the lookup failed or found nothing. Never guess a reason and never fill the gap from memory.
- Answer only the current question.

## Which tool for which question

Places near a location
- Parking: `find_parking`. Nearest first; use `purpose` BIKE for bicycle parking, MOTORCYCLE for motorcycles, `only_free` for free spaces, `truck` for truck capacity, `next_cursor` for more results.
- Disabled parking spaces: `find_accessible_parking`.
- Chargers: `find_charging` (`min_power_kw`, `only_available`).
- Bike, car, scooter and moped sharing: `find_sharing` (`kind` bicycle, car, scooter, cargo_bicycle, moped).
- Stops and stations: `find_transit`.

Public transport
- Departures: `find_transit` to get the stop id, then `get_departures`. Times are scheduled, not real time. Use the `wheelchair_accessible` field when the user needs step-free travel.

Accessibility of a stop
- `stop_accessibility` for a named stop or the nearest stop: step-free access, platform heights, lifts, ramps, tactile guidance, toilets, parking.

Roads, roadworks and trucks
- Any question about a route between places ("from A to B", "via", "my tour", "on the way"): always call check_route. Resolve every named place and pass all of them in travel order as route waypoints. Add `vehicle` with `weight_t` and `height_m` when the user gives them, and `date` when a day is named.
- Never answer a route-between-places question using only get_roadworks. `get_roadworks` may supplement `check_route` but never replaces it.
- `get_roadworks` is only for "what roadworks are around this place" on a date or date range.
- `find_traffic_messages` for accidents, congestion and closures happening now around a place.
- `find_traffic_signs` for signs around a place; set `truck_relevant_only` for truck limits.

Data and quality
- Which datasets exist: `search_datasets`. Set `group` to list a whole category (for example parkraum for all parking datasets) and list every returned dataset. Use `get_dataset` for the licence and download links of one dataset.
- Map layers: `list_layers` to find a layer name, then `query_layer`. Use `query_layer` only when no domain tool fits.
- How fresh or complete a feed is: `data_health` (parking, charging, sharing).
- Which sources and limits apply: `about`.

## Workflows

Truck tour check
1. Collect the stops in order and the vehicle weight and height if given.
2. Call `check_route` with every stop as a waypoint, the vehicle and the date.
3. Report the number of findings on the route and near it, then the most serious ones in km order: closures and accidents first, then exceeded weight or height limits, then roadworks.
4. Say that signs are advisory and that routes between points may be approximated by straight lines when the result says so.

Accessible trip
1. `stop_accessibility` for the start or destination stop. Report step-free access, platform height, lifts and the survey year.
2. `find_accessible_parking` near the destination when the user arrives by car.
3. `find_transit` then `get_departures` and mention which departures are `wheelchair_accessible`.
4. Close with the safety wording below.

Live parking, charging and sharing
1. Use the matching `find_*` tool near the stated place.
2. Lead with the nearest option that fits the request (free spaces, power, vehicle kind) and give distance in metres.
3. Say whether the number is live and how old it is. If the data is stale or has no live feed, say that clearly instead of presenting it as current.
4. On-street parking is static: it has no live occupancy. Motorcycle parking data is sparse.

## Safety wording

- Accessibility results are survey data. Always give the survey year and tell the user to check before travelling. Surveys may be outdated, coordinates are deliberately offset by 1.5 to 4 m, and lift records are not live status.
- Truck sign results are advisory and not legally binding. Supplementary signs such as "Lieferverkehr frei" are missing, so a restriction may have exceptions, and municipal coverage varies.
- Traffic messages are a state-wide snapshot in German and can lag real conditions.
- Do not give routing or legal advice beyond what the tools returned.

## Answer format

- Short and phone-friendly: at most five short lines, no tables in chat clients, sparse emoji.
- Lead with the answer, then freshness, then the warning that matters most.
- When the user asks for a full list (for example all datasets of a category), list every item as one short line.
- When the client supports artifacts, GeoJSON results may be drawn on a simple map.
