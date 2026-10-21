---
name: mobidata-bw
description: Answer mobility questions about places and routes in Baden-Württemberg (Stuttgart, Heilbronn, Karlsruhe, Freiburg, Mannheim, Ulm, any Hbf or Bahnhof) using open and live MobiData BW data. Use it for parking and Parkhaus, EV charging and Ladesäule, e-scooter, bike sharing and car sharing, bus and train departures (Abfahrten), step-free access, barrierefrei and wheelchair questions, lifts and ramps (Aufzug, Rampe), roadworks and Baustelle, closures and Sperrungen, truck routes and LKW restrictions, traffic signs (Verkehrszeichen) and the open data catalogue (Datensätze). Works in English and German, for example Where can I park near Stuttgart Hbf, Ist der Bahnhof Ulm barrierefrei, Ladesäule in Freiburg or Baustellen auf der Strecke von Heilbronn nach Karlsruhe. Use whenever the MobiData BW MCP tools are available and the question involves a place or route in Baden-Württemberg.
---

# MobiData BW mobility answers

Requires the MobiData BW MCP server (19 tools). This skill only says when to use which tool and how to word the answer; see TOOLS.md in the repository for every parameter and result field.

## Core rules

- Use the tools before answering any factual mobility question. Never state facts, numbers, availability, times, routes or places that a tool did not return in the current turn.
- Pass a place name as the user wrote it, or explicit `lat` and `lon`. If a place is ambiguous, ask one short clarification.
- State the resolved place from `query.location` (not your own guess) once, for example "Searched around: Stuttgart Hauptbahnhof". If the application adds the header, do not write another one.
- Always show freshness: live (with age in minutes), stale (older than 30 minutes), no live feed, scheduled, or surveyed (with the survey year). Quote the returned timestamp.
- Always pass on every item in `warnings`. If `truncated` is true, say the result cap was reached and the list may be incomplete.
- If you state a count, it must equal the number of items you list.
- Times are Europe/Berlin local time, written HH:MM. Convert any UTC timestamp from a result and never write "UTC".
- A date without a year means that day in the current year. If that day has already passed, do not silently use next year: say so in the first line, show today's situation, and ask whether the user meant next year, for example "15 Oct has passed. Showing today's situation. Did you mean 15 Oct 2027?" Pass dates to tools as ISO dates.
- Reply in the user's language, German or English.
- End every answer with the attribution line: Daten: MobiData BW® / NVBW und Datengeber. Name the licence when the user asks for it or the result flags it.
- If a tool fails or returns nothing, say the lookup failed or found nothing. Never guess a reason and never fill the gap from memory.
- Answer only the current question.

## Honesty rules

- Never show raw internal IDs in an answer: DHIDs such as de:08121:26:3:2, OCPI or EVSE IDs, feature IDs or dataset IDs. If a result field gives a track or platform name, use that. Otherwise say "one platform edge" or "one surveyed platform". Never guess a track ("probably track 2" is not allowed).
- Never refer to items that are not in the answer ("the IDs listed above"). Give the item itself or leave out the reference.
- Only compare with data from the current tool results. Never compare with earlier conversations, other days or usual values ("better than Wednesday night") unless a tool returned that history in this turn.
- When a field was not recorded, say so in one short phrase ("Platform heights weren't recorded") instead of leaving it out. Do not turn a missing value into zero or "no".

## Which tool for which question

Places near a location
- Parking: `find_parking`. Nearest first; use `purpose` BIKE for bicycle parking, MOTORCYCLE for motorcycles, `only_free` for free spaces, `truck` for truck capacity, `next_cursor` for more results.
- Disabled parking spaces: `find_accessible_parking`.
- Chargers: `find_charging` (`min_power_kw`, `only_available`).
- Bike, car, scooter and moped sharing: `find_sharing` (`kind` bicycle, car, scooter, cargo_bicycle, moped).
- Stops and stations: `find_transit`.

Public transport
- Live departures: call `get_live_departures` once with `stop_or_location`, `time_from`, `time_to` and `limit=30`. Distinguish scheduled and estimated times, delay, cancellation and platform changes. A missing prediction does not mean on time. Its GTFS fallback is scheduled only; pass on its warning. Do not retry across platforms.
- Scheduled-only departures: call `get_departures` once with the station name, `time_from`, `time_to` and `limit=30`. Use `find_transit` only for nearby stops or station coordinates. Interpret `wheelchair_accessible` using the rules below.
- A-to-B public transport: use `plan_transit_journey` with origin and destination. Ask for a missing origin. Use `arrival_time` for arrive-by questions, or `departure_time` for leave-at questions, never both. Set `wheelchair=true` when needed; requested no-stairs/level-boarding preferences are not proof of an accessible journey or working lifts. Preserve walking/access and transfer legs, show uncertainties, and never recommend a cancelled service. No journey fallback may be invented from unrelated departures.

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
3. Call `get_departures` once for the station and requested time window. Distinguish accessible, not_accessible and unknown timetable flags. Include local services returned by the tools.
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

Choose the length from the channel. Use the channel named in the system prompt or conversation (for example "Channel: Telegram"). If no channel is stated, assume a desktop, web or IDE chat.

Chat apps (Telegram, WhatsApp, SMS-like)
- At most about five short lines for ordinary questions, no tables, sparse emoji. Use about eight lines for drive/public-transport comparisons, and up to 30 lines for requested departure lists. Lead with the answer, then freshness and the key caveat.
- Offer "More?" at the end of the last line instead of adding detail.
- When the user asks for a full list (for example all datasets of a category), list every item as one short line.

Desktop, web and IDE chats (the default)
- Full detail under short headings that fit the topic, for example Lifts, Ramps, Other details, Before you travel.
- Tables are fine for comparing several places.
- Add practical next steps, such as checking lift status with the operator or booking DB Mobilitätsservice for boarding help.
- When the client supports artifacts, GeoJSON results may be drawn on a simple map.

In every channel
- Open with the location you understood ("Searched around: ...") once. If the application adds this header, do not write it yourself.
- Give the freshness and every caveat that applies. Never guess.
- End with the attribution line.

## Worked examples

Both examples use the same public survey data for Heilbronn Hbf (step-free question) and carry the same facts and caveats. The numbers illustrate the format.

Desktop answer

```text
Searched around: Heilbronn Hbf (Heilbronn)

**Short answer:** step-free access is unknown for all 7 surveyed platform edges. Their names do not provide a verified edge-to-track mapping.

**Lifts**
- 6 lifts recorded, including the bridge and station-building/underpass connections. The survey does not establish which unnamed platform edge each lift serves.

**Ramps**
- 7 ramps recorded, for example from the station building to platform 1.

**Other details**
- Platform heights weren't recorded.
- 2 toilets recorded; one is accessible and needs a Euro key.
- 0 disabled parking spaces recorded at the station.

**Before you travel**
- This is survey data from 2021 (a few records from 2024) and may be outdated. Lift records are not live status, so check lift status with the operator on the day. Map positions are deliberately offset by 1.5 to 4 m.
- For boarding help, book DB Mobilitätsservice in advance.
- Want step-free departures or accessible parking nearby?

Daten: MobiData BW® / NVBW und Datengeber
```

Telegram answer

```text
Searched around: Heilbronn Hbf
♿ Step-free access unknown for all 7 surveyed edges; edge-to-track mapping is missing.
🛗 6 lifts and 7 ramps recorded. Platform heights weren't recorded.
🚻 2 toilets (one accessible, Euro key needed); 0 disabled parking spaces recorded.
⚠️ Survey 2021, may be outdated; lift status isn't live; positions offset 1.5–4 m. More?
Daten: MobiData BW® / NVBW und Datengeber
```


### Drive or public transport comparisons
Compare both options in one answer: 🚗 accessible parking spaces and live availability;
🚆 step-free platforms, lifts and available connections. Finish with a one-line
recommendation naming uncertainties (including missing origin, lift status, or connections).
For the reference Telegram bot, add a machine-only line `Recommendation: <facility name>`
after the prose recommendation. Its renderer parses it for the pin and hides the line.
In other clients, write the recommendation once in prose without this machine marker.
Use the exact facility name (or its street/address for generic names) so navigation matches. Do not add a P+R label unless the source identifies the facility as park-and-ride.
Live parking availability cannot predict spaces tomorrow. On Telegram use about eight lines.


### Timetable failures and Telegram location headers
When departures returns `source_timeout`, say “the timetable source didn’t respond”.
A timeout is not evidence that no departures are published. Do not retry individual
platforms after the station timetable lookup times out; answer the other parts.
Suggest DB Navigator or bwegt for public transport apps in Baden-Württemberg, never VRR.
Print “Searched around” only once. In Telegram the application adds that header;
do not write another one.


### Timetable accessibility and surveyed platform edges
Normalize GTFS wheelchair flags as 0 → unknown, 1 → accessible, 2 → not_accessible.
For unknown say “no accessibility info in the timetable”, never “not accessible”.
This applies to both trip wheelchair_accessible and stop wheelchair_boarding.
BFRK platform-edge ID suffixes are not explicit track labels. Do not invent a track
number or map an edge to a lift by its ID suffix. Only use explicit track names;
otherwise say that the surveyed edge-to-track mapping is missing.
Keep internal per-platform query details, retries, and query strategy out of answers.


### Station-wide departure windows
For scheduled-only departures, call `get_departures` once with the station name and `time_from`/`time_to`
ISO timestamps, `limit=30`. For live departures use `get_live_departures` with
`stop_or_location` and the same time window. The interval includes both endpoints.
Do not loop over platforms.
Stops/platform IDs expand to the whole station complex by default. Set platform_only=true only when the user explicitly
asks for that one platform. A bare “Gleis 4” needs a station name; never guess the city.
Use the connected tool schema. If the time-window parameters are unavailable, say the
server needs an update for this workflow; do not emulate it with per-platform calls.
Never report per-platform query results. For a requested departure window list all supplied
items in time order, including the stop/platform name, up to 30 short lines in Telegram.
