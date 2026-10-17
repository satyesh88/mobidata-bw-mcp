# Server departures diagnostic

Read-only measurements on `hetzner-mcp`, through
`/opt/mobidata-bw-mcp/venv/bin/python -B`, for Heilbronn Hbf,
Monday 19 October 2026 at 09:00 Europe/Berlin, limit 10.

The service imports an old wheel from
`venv/lib/python3.14/site-packages/mobidata_bw_mcp`, despite the checkout being
at 7446bc8. Pulling and restarting does not update this wheel. The updated MCP
unit loads source via PYTHONPATH, as the bot already does.

| Measurement | Installed wheel | Checkout 7446bc8 | Candidate in memory |
| --- | ---: | ---: | ---: |
| Stop lookup | absent | 178.4 ms | 149.0 ms |
| Stop IDs | 0 (name used as ID) | 9 | 9 |
| Cold total | 15540.2 ms | 940.8 ms | 394.5 ms |
| Cached total | no cache | 0.4 ms | 0.3 ms |
| Departures | 0 | 10 | 10 |

Candidate query timings from the server venv:

- Stop-name query: 133.4 ms; parent/child query: 14.5 ms.
- Batched stop_times pages: 14.6, 17.9, 14.5, 15.5, 14.7 ms.
- One arrivals_departures query for all nine IDs: 165.5 ms.
- Formatting: 0.2 ms.

Journal inspection over the preceding 24 hours found departures calls taking
12092–31046 ms, HTTPStatusError entries, and no prewarm or detailed departures
timing entries, consistent with the stale package. No server files or services
were changed by the diagnostic. Candidate modules were loaded only in memory.

The accessible-parking source returns Bahnhof West at 49.1425348, 9.2171518,
without an address. This differs from the search point 49.1431403, 9.2076637.
Use those facility coordinates and its name when no address is supplied;
do not substitute the geocoded station address or invent a street or P+R status.

For the current update procedure use the [source-only migration in UPDATING.md](UPDATING.md#stale-wheel-lesson-and-one-time-migration).
It confirms PYTHONPATH and the Python module entry point before uninstalling the stale
project wheel. The venv retains third-party dependencies. Restart only the MCP and bot
services. The diagnostic itself did not perform this migration.

Repeat the read-only measurement after updating:

```sh
cd /opt/mobidata-bw-mcp
PYTHONPATH=src /opt/mobidata-bw-mcp/venv/bin/python -B scripts/diagnose_departures.py
journalctl -u mobidata-mcp --since "10 minutes ago" --no-pager | grep -E 'prewarm|departures'
```
