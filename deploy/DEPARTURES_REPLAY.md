# Departures agent replay and server window output

The server and local configuration both select claude-haiku-5-5 with ten tool rounds.
Replays use the actual agent, real MCP tools and the repository skill. The request clock
is fixed to 18 October 2026, 12:00 Europe/Berlin. Each replay has empty conversation history;
it does not reconstruct the historical Telegram session. Model tool choices can vary.

Sequences show dispatch order; calls in one model turn may run concurrently.
Tool arguments below are the calls actually dispatched. Coordinates are rounded to three
decimals for logging only. Production logs now include both arguments and requested_arguments
for comparison. Telegram message bodies and credentials are not logged.

## Original wheelchair comparison: baseline

Skill SHA-256: 689c4cfd53e27e764026e3d20594fd3ff1208328b33dbbd854a29c023ad496bf

```json
{"tool": "find_accessible_parking", "arguments": {"location": {"label": "Heilbronn Hbf", "lat": 49.143, "lon": 9.211}, "radius_m": 1000}}
{"tool": "stop_accessibility", "arguments": {"stop_or_location": "Heilbronn Hbf"}}
{"tool": "find_transit", "arguments": {"location": "Heilbronn Hbf", "radius_m": 500}}
{"tool": "get_departures", "arguments": {"stop_or_station_id": "de:08121:26", "date": "2026-10-19", "from_time": "2026-10-19T08:30:00+02:00", "limit": 10}}
{"tool": "find_parking", "arguments": {"location": {"label": "Heilbronn Hbf", "lat": 49.143, "lon": 9.211}, "purpose": "CAR", "only_free": true, "radius_m": 1000, "limit": 5}}
{"tool": "get_departures", "arguments": {}}
{"tool": "get_departures", "arguments": {"stop_or_station_id": "de:08121:26", "date": "2026-10-19", "from_time": "2026-10-19T08:50:00+02:00", "limit": 10}}
```

## Same original question: updated agent

Skill SHA-256: 05c4a08c72afaa314d7566bed667e678abcb438921dac4820eebbe7d6245dd73

```json
{"tool": "find_accessible_parking", "arguments": {"location": "Heilbronn Hbf", "radius_m": 1000}}
{"tool": "stop_accessibility", "arguments": {"stop_or_location": "Heilbronn Hbf"}}
{"tool": "find_transit", "arguments": {"location": "Heilbronn Hbf", "radius_m": 500}}
{"tool": "get_departures", "arguments": {"stop_or_station_id": "Heilbronn Hbf", "time_from": "2026-10-19T08:30:00+02:00", "time_to": "2026-10-19T10:00:00+02:00", "limit": 30}}
{"tool": "find_parking", "arguments": {"location": "Heilbronn Hbf", "radius_m": 1000, "only_free": true}}
```

## Explicit Monday 09:00–09:30 window: updated agent

Skill SHA-256: 05c4a08c72afaa314d7566bed667e678abcb438921dac4820eebbe7d6245dd73

```json
{"tool": "find_transit", "arguments": {"location": "Heilbronn Hbf"}}
{"tool": "get_departures", "arguments": {"stop_or_station_id": "Heilbronn Hbf", "time_from": "2026-10-19T09:00:00+02:00", "time_to": "2026-10-19T09:30:00+02:00", "limit": 30}}
```

The baseline did not reproduce the historical platform loop: it instead made three
departure calls, including an invalid empty call and two different starting times, both
limited to ten. An intermediate prompt-only replay did choose de:08121:26:4:4 for the
09:00–09:30 window. Tool-side expansion returned the whole station; the final agent also
canonicalizes that ID to Heilbronn Hbf before dispatch. Explicit platform_only requests
remain scoped to a platform. A bare platform name without station context is ambiguous.

## Server output

The final read-only server run queried 17 stop IDs and returned 28 rows. Lookup: 166.9 ms;
PostgREST: 471.9 ms; formatting: 0.3 ms; measured total: 639.9 ms. Cached total: 0.5 ms.
The list includes S4, S41 and S42 at Hbf/Willy-Brandt-Pl. and includes the 09:30 boundary.
Wheelchair codes below are the normalized GTFS semantics: 0 unknown, 1 accessible,
2 not_accessible. The API exposes enums; the diagnostic prints their numeric equivalents.
The source has duplicate rows and conflicting trip accessibility flags. They are preserved,
not silently reconciled or treated as proof about lift/platform access.

[Complete stdout including every query](DEPARTURES_0900_OUTPUT.txt)

```text
TIME | LINE | DESTINATION | STOP | WHEELCHAIR_GTFS (0 unknown, 1 accessible, 2 not_accessible)
09:00 | 13 | Heilbronn Allee Post West | Heilbronn Hbf/Willy-Brandt-Pl. (Steig A) | 2
09:03 | S42 | Sinsheim, Hauptbahnhof | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 2 | 2
09:03 | S42 | Sinsheim, Hauptbahnhof | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 2 | 1
09:05 | 640 | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:05 | 640 | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:06 | S4 | Öhringen-Cappel | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 3 | 1
09:06 | S4 | Öhringen-Cappel | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 3 | 2
09:06 | RB83 | Hessental Bahnhof | Heilbronn Hauptbahnhof Gleis 1 | 2
09:06 | RE10a | Mannheim, Hauptbahnhof | Heilbronn Hauptbahnhof Gleis 5 | 2
09:10 | 620 | Heilbronn Hbf/Busbahnhof | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:11 | 1 | Klingenberg Schlüsseläcker | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:12 | RE 8 | Stuttgart Hauptbahnhof | Heilbronn Hauptbahnhof Gleis 6 | 2
09:14 | 13 | Böckingen Westfriedhof | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:14 | 13 | Böckingen Westfriedhof | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:17 | S42 | Heilbronn Hbf/Willy-Brandt-Pl. | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 2 | 2
09:17 | S42 | Heilbronn Hbf/Willy-Brandt-Pl. | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 2 | 1
09:18 | S41 | Mosbach, Bahnhof | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 3 | 1
09:18 | S41 | Mosbach, Bahnhof | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 3 | 2
09:18 | 61 | Sontheim Jörg-Ratgeb-Platz | Heilbronn Hbf/Willy-Brandt-Pl. (Steig A) | 2
09:18 | 61 | Sontheim Jörg-Ratgeb-Platz | Heilbronn Hbf/Willy-Brandt-Pl. (Steig A) | 2
09:22 | S4 | Schwaigern(Württ) West | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 1 | 2
09:22 | RE45 | Heilbronn Hauptbahnhof | Heilbronn Hauptbahnhof Gleis 7 | 2
09:22 | S4 | Schwaigern(Württ) West | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 1 | 1
09:23 | 61 | Frankenbach (HN) Maihalde | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:26 | 641 | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:26 | 641 | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | 2
09:28 | MEX18 | Osterburken, Bahnhof | Heilbronn Hauptbahnhof Gleis 3 | 2
09:30 | MEX18 | Tübingen Hauptbahnhof | Heilbronn Hauptbahnhof Gleis 5 | 2
```

The final window replay listed all 28 departure rows, then explained the conflicting flags.
It did not produce per-platform empty-result statements. The pin title and button both
use the facility short name, for example Heilbronn Hbf.

## Reproduce locally

```sh
PYTHONPATH=src .venv/bin/python scripts/replay_agent.py
```

This reads the bot settings from .env, invokes the configured model and tools, and never
sends a Telegram message. Use --question to replay another case.

## Update the already-migrated source-only services

```sh
cd /opt/mobidata-bw-mcp &&
git pull --ff-only origin main &&
sudo systemctl restart mobidata-mcp &&
sudo systemctl restart mobidata-bot
```

No server files were changed and no services were restarted by this diagnostic.
