"""Generate TOOLS.md. Parameters come from the live MCP schema; descriptive text is curated below.

Run: uv run python scripts/generate_tools_doc.py
"""

import asyncio
from pathlib import Path
from typing import Any

from mobidata_bw_mcp.server import mcp

CKAN = "CKAN catalogue (mobidata-bw.de/api/3/action/)"
WFS = "GeoServer WFS (api.mobidata-bw.de/geoserver)"
DL = "Datenlizenz Deutschland - Namensnennung 2.0"

# name -> (category, source, licence, returns, caveats, example, parameter notes)
TOOLS: dict[str, dict[str, Any]] = {
    "search_datasets": {
        "category": "Discovery",
        "source": CKAN,
        "licence": "Varies per dataset (reported in each item)",
        "returns": "title, slug, description (160 characters), licence, licence_missing, "
        "last_modified, formats. query.total_matches gives the full match count.",
        "caveats": [
            "Free-text search ranks loosely; use group to list a whole category exactly.",
            "Results are cached for 1 hour.",
        ],
        "example": "Show all parking datasets (group parkraum).",
        "params": {
            "query": "Search words. Empty or blank matches everything.",
            "limit": "Maximum datasets returned (1 to 200).",
            "group": "One of the 10 website categories, for example parkraum or "
            "oeffentlicher-personenverkehr.",
        },
    },
    "get_dataset": {
        "category": "Discovery",
        "source": CKAN,
        "licence": "Varies per dataset",
        "returns": "title, slug, full description, licence, last_modified and the list of "
        "resources with their current download URLs.",
        "caveats": ["Use the slug from search_datasets as dataset_id."],
        "example": "Give me the licence and download links of the dataset bikesh.",
        "params": {"dataset_id": "Dataset slug, for example bikesh."},
    },
    "list_layers": {
        "category": "Discovery",
        "source": WFS,
        "licence": "See individual dataset metadata",
        "returns": "name, title and geometry_attribute of each of the 13 current WFS layers.",
        "caveats": ["Cached for 24 hours."],
        "example": "Which map layers can you query?",
        "params": {},
    },
    "query_layer": {
        "category": "Generic",
        "source": WFS,
        "licence": "See individual dataset metadata",
        "returns": "properties (all layer attributes), geometry, lat, lon and distance_m when a "
        "location is given. Coordinates are always WGS84.",
        "caveats": [
            "Use layer names from list_layers.",
            "filter accepts simple comparisons only; semicolons, comments and || are rejected.",
            "Long line features (for example the cycle network) are matched by a representative "
            "point, so use a radius of 1,000 m or more for them.",
        ],
        "example": "Show bicycle service points within 2 km of Freiburg Hauptbahnhof.",
        "params": {
            "layer": "Full layer name, for example MobiData-BW:bicycle_service_points.",
            "location": "Place name or {lat, lon}. Give location or bbox.",
            "bbox": "{min_lat, min_lon, max_lat, max_lon}. Alternative to location.",
            "radius_m": "Search radius around location.",
            "filter": "Optional simple CQL comparison, for example name = 'x'.",
            "limit": "Maximum features returned.",
        },
    },
    "find_parking": {
        "category": "Parking",
        "source": "ParkAPI v3 (api.mobidata-bw.de/park-api), 71 upstream sources",
        "licence": DL,
        "returns": "id, name, type, address, capacity, free_now, max_height_m, lat, lon, "
        "distance_m, is_live, age_minutes, updated_at. Sorted nearest first.",
        "caveats": [
            "Fetches every site in the radius, sorts by distance, then pages with next_cursor.",
            "In very dense areas (over about 1,000 sites) the radius is narrowed and a warning "
            "says so.",
            "On-street records are static; they have no live occupancy.",
            "Motorcycle parking is published by very few sources.",
        ],
        "example": "Where can I park near Heilbronn Hauptbahnhof?",
        "params": {
            "location": "Place name or {lat, lon}.",
            "radius_m": "Search radius.",
            "purpose": "CAR, BIKE (stands and lockers), MOTORCYCLE or ITEM (bike boxes).",
            "only_free": "Only sites with free spaces right now.",
            "truck": "Only sites with truck capacity; uses truck capacity and free spaces.",
            "limit": "Page size.",
            "cursor": "Offset from the previous result's next_cursor.",
        },
    },
    "find_accessible_parking": {
        "category": "Accessibility",
        "source": "ParkAPI v3 plus BFRK accessibility surveys (NVBW CSV files)",
        "licence": DL,
        "returns": "id, name, capacity_disabled, lat, lon, distance_m, source_label, "
        "survey_year, survey_date, network, type; live fields for ParkAPI sites.",
        "caveats": [
            "BFRK surveys were taken in different years and may be outdated.",
            "BFRK coordinates are deliberately offset by about 1.5 to 4 m.",
        ],
        "example": "Are there disabled parking spaces near Stuttgart Hauptbahnhof?",
        "params": {
            "location": "Place name or {lat, lon}.",
            "radius_m": "Search radius.",
            "limit": "Maximum items returned.",
        },
    },
    "stop_accessibility": {
        "category": "Accessibility",
        "source": "BFRK accessibility surveys (CKAN datasets for SPNV stations and OEPNV stops)",
        "licence": DL,
        "returns": "name, municipality, network, step_free and step_free_basis, platform_access, "
        "platform_or_curb_heights_cm, stairs_count, ramps, elevators, tactile_guidance, "
        "wheelchair_toilets, disabled_parking_spaces, bottlenecks, photo_links, survey_years.",
        "caveats": [
            "Surveyed infrastructure, not live status; elevator records are not live outages.",
            "Surveys may be outdated.",
        ],
        "example": "Is Heidelberg Hauptbahnhof step-free?",
        "params": {
            "stop_or_location": "Stop name, or a place or {lat, lon} to find the nearest stop."
        },
    },
    "find_charging": {
        "category": "E-mobility",
        "source": WFS + ", layer charge_points",
        "licence": "See individual dataset metadata",
        "returns": "id, name, operator, address, city, max_power_kw, available, total, charging, "
        "out_of_order, lat, lon, distance_m, is_live, age_minutes, updated_at.",
        "caveats": [
            "Many locations have no current status; the warning counts them.",
            "Returns every location in the radius (up to 1,000); there is no limit setting.",
        ],
        "example": "Find chargers within 1 km of Mannheim Hauptbahnhof.",
        "params": {
            "location": "Place name or {lat, lon}.",
            "radius_m": "Search radius.",
            "min_power_kw": "Only locations whose maximum power is at least this value.",
            "only_available": "Only locations with at least one free connector.",
        },
    },
    "find_sharing": {
        "category": "Sharing",
        "source": WFS + ", layers sharing_stations and sharing_vehicles (GBFS feeds)",
        "licence": "See individual dataset metadata",
        "returns": "item_type (station or vehicle), operator, name, kind, propulsion_type, "
        "available counts, virtual_station_inventory, count_semantics, current_range_m, "
        "max_range_m, battery_pct, rental_link, lat, lon, distance_m, is_live, updated_at.",
        "caveats": [
            "Counts at virtual stations are inventory, not physically parked vehicles.",
            "Free-floating vehicles are reported individually.",
        ],
        "example": "Are there e-scooters near Stuttgart Hauptbahnhof?",
        "params": {
            "location": "Place name or {lat, lon}.",
            "radius_m": "Search radius.",
            "kind": "any, bicycle, car, scooter, cargo_bicycle or moped.",
        },
    },
    "find_transit": {
        "category": "Public transport",
        "source": WFS + ", layers transit_stops and transit_stations_with_served_routes",
        "licence": "CC BY 4.0",
        "returns": "id, name, item_type (stop or station), lat, lon, distance_m.",
        "caveats": ["Scheduled timetable data only; no real-time information."],
        "example": "Which stops are near Konstanz Bahnhof?",
        "params": {"location": "Place name or {lat, lon}.", "radius_m": "Search radius."},
    },
    "get_departures": {
        "category": "Public transport",
        "source": "GTFS API (api.mobidata-bw.de/gtfs, arrivals_departures)",
        "licence": "CC BY 4.0",
        "returns": "route, headsign, departure, scheduled_time, stop_id, stop_name, "
        "station_name, wheelchair_accessible.",
        "caveats": [
            "Scheduled times, not real time.",
            "Dates close to today may not be published yet.",
            "The timetable database can time out; retrying usually works.",
        ],
        "example": "When does the next train leave Heidelberg Hauptbahnhof on Monday at 08:00?",
        "params": {
            "stop_or_station_id": "Stop or station id from find_transit, for example "
            "de:08416:10508:0:4.",
            "date": "Service date (ISO). Defaults to today.",
            "from_time": "Only departures from this time (ISO datetime).",
            "limit": "Maximum departures.",
        },
    },
    "get_roadworks": {
        "category": "Traffic events",
        "source": "Roadworks GeoJSON (api.mobidata-bw.de/datasets/traffic/roadworks)",
        "licence": DL,
        "returns": "id, street, type, subtype, description, direction, start, end, lat, lon, "
        "distance_m, geometry_type.",
        "caveats": [
            "Defaults to today when no date is given.",
            "active_on cannot be combined with active_from or active_to.",
            "Cached for 15 minutes.",
        ],
        "example": "Are there roadworks in Ulm today?",
        "params": {
            "location": "Place name or {lat, lon}. Give location or bbox.",
            "bbox": "{min_lat, min_lon, max_lat, max_lon}.",
            "radius_m": "Search radius around location.",
            "active_on": "A single date (ISO).",
            "active_from": "Start of a date range.",
            "active_to": "End of a date range.",
        },
    },
    "find_traffic_signs": {
        "category": "Transport networks",
        "source": "Traffic signs GeoJSON (mobidata-bw.de/daten/portal/VZ-Daten)",
        "licence": DL,
        "returns": "sign_code, raw_sign_code, meaning, municipality, lat, lon, distance_m, "
        "last_updated.",
        "caveats": [
            "Advisory only, not legally binding.",
            "Supplementary signs (for example Lieferverkehr frei) are not included.",
            "Municipal coverage varies. Truck-relevant codes: 253, 262, 263, 264, 265, 266, 277.",
        ],
        "example": "Are there truck restrictions near Heilbronn?",
        "params": {
            "location": "Place name or {lat, lon}. Give location or bbox.",
            "bbox": "{min_lat, min_lon, max_lat, max_lon}.",
            "radius_m": "Search radius around location.",
            "sign_codes": "Only these sign numbers, for example [\"265\"].",
            "truck_relevant_only": "Only the truck-relevant codes listed above.",
        },
    },
    "find_traffic_messages": {
        "category": "Traffic events",
        "source": "DATEX II traffic messages (api.mobidata-bw.de/datasets/traffic/incidents)",
        "licence": DL,
        "returns": "id, category, type, severity, description (German), location_description, "
        "start, end, lat, lon, distance_m. data_timestamp is the feed publication time.",
        "caveats": [
            "State-wide snapshot that may lag real conditions; cached for 5 minutes.",
            "Severity is high for accidents and for texts mentioning a closure.",
            "Records with the same text and place are merged.",
        ],
        "example": "Any accidents or road closures near Stuttgart right now?",
        "params": {
            "location": "Place name or {lat, lon}.",
            "radius_m": "Search radius.",
            "limit": "Maximum messages.",
        },
    },
    "check_route": {
        "category": "Route check",
        "source": "Roadworks, DATEX II traffic messages and traffic signs; OpenRouteService "
        "HGV routing when configured",
        "licence": DL,
        "returns": "Findings ordered by km_from_start: kind (roadwork, traffic_message or "
        "traffic_sign), route_relation (on_route or near_route), distance_to_route_m, severity, "
        "description, plus sign_code, limit and vehicle_exceeds_limit for signs. The first "
        "warning is a count summary.",
        "caveats": [
            "A list of points is routed with OpenRouteService when a key is set; otherwise "
            "straight lines approximate the route and the buffer is at least 500 m.",
            "If the traffic message feed is down, roadworks and signs are still returned and "
            "a warning says incidents are missing.",
            "Sign results are advisory.",
        ],
        "example": "I'm driving a 40 t truck, 4 m high, from Karlsruhe via Pforzheim to "
        "Stuttgart. Any restrictions?",
        "params": {
            "route": "GeoJSON LineString, or a list of {lat, lon} waypoints in travel order.",
            "buffer_m": "Distance on each side of the route (1 to 1,000 m).",
            "date": "Travel date (ISO). Defaults to today.",
            "vehicle": "{weight_t, height_m}; used to flag weight and height limits that are "
            "exceeded.",
        },
    },
    "data_health": {
        "category": "Quality",
        "source": "ParkAPI v3 and GeoServer WFS (charging, sharing)",
        "licence": DL,
        "returns": "Per dataset: groups (live_and_fresh, live_capable_but_stale, no_live_feed), "
        "live_percent and its basis, median_age_min, max_age_min, oldest_site, stale_sites, "
        "top_regions, area_used, status.",
        "caveats": [
            "Fresh means updated within 30 minutes.",
            "Parking defaults to off-street sites; on-street records have no live feed.",
        ],
        "example": "How fresh is the parking data in Heilbronn?",
        "params": {
            "region": "City or region name; omit for all of Baden-Württemberg.",
            "dataset": "parking, charging, sharing or all.",
            "parking_scope": "off_street, on_street or all.",
        },
    },
    "about": {
        "category": "Meta",
        "source": "This server",
        "licence": "Apache-2.0 (server code)",
        "returns": "name, version, description, sources, licences, caveats, contact. Also "
        "available as the MCP resource mobidata://about.",
        "caveats": ["This independent project is not affiliated with or endorsed by NVBW."],
        "example": "What data sources do you use and under which licences?",
        "params": {},
    },
}

ORDER = list(TOOLS)


def _type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return "one of " + ", ".join(str(value) for value in schema["enum"])
    kinds: list[str] = []
    for option in schema.get("anyOf") or [schema]:
        kind = option.get("type")
        if kind == "null":
            continue
        if kind == "array":
            kind = f"list of {option.get('items', {}).get('type', 'items')}"
        kinds.append(kind or "object")
    return " or ".join(dict.fromkeys(kinds)) or "object"


def _default(name: str, schema: dict[str, Any], required: set[str]) -> str:
    if name in required:
        return "required"
    default = schema.get("default")
    return "optional" if default in (None, "") else f"default `{default}`"


async def build() -> str:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    missing = set(tools) ^ set(TOOLS)
    if missing:
        raise SystemExit(f"Curated notes out of sync with the server: {sorted(missing)}")
    lines = [
        "# MobiData BW MCP: Tool Reference",
        "",
        f"This reference covers all {len(tools)} tools. Parameter names, types and defaults are "
        "generated from the running server; regenerate with "
        "`uv run python scripts/generate_tools_doc.py`.",
        "",
        "## Result format",
        "",
        "Every data tool returns the same envelope:",
        "",
        "| Field | Meaning |",
        "|---|---|",
        "| `query` | The resolved request, including the geocoded place for location searches |",
        "| `count` | Number of items in this response |",
        "| `items` | The results |",
        "| `truncated` and `next_cursor` | Set when more results exist; `next_cursor` pages "
        "`find_parking` |",
        "| `source` | Dataset, endpoint, licence and attribution text |",
        "| `data_timestamp` | Newest data time where the source provides one |",
        "| `warnings` | Freshness, coverage and licence caveats; always show these to users |",
        "",
        "Fields with no value are omitted from items. Live items carry `is_live`, "
        "`age_minutes` and `updated_at`; data older than 30 minutes is treated as not live.",
        "",
        "## Overview",
        "",
        "| Tool | Category | What it does |",
        "|---|---|---|",
    ]
    for name in ORDER:
        summary = " ".join(tools[name].description.split("\n\n")[0].split())
        lines.append(f"| [`{name}`](#{name}) | {TOOLS[name]['category']} | {summary} |")
    for name in ORDER:
        tool, notes = tools[name], TOOLS[name]
        props = tool.inputSchema.get("properties", {})
        required = set(tool.inputSchema.get("required", []))
        lines += ["", f"## {name}", "", " ".join(tool.description.split("\n\n")[0].split()), ""]
        lines += [f"Example question: {notes['example']}", ""]
        if props:
            header = "| Parameter | Type | Required or default | Description |"
            lines += [header, "|---|---|---|---|"]
            for key, schema in props.items():
                lines.append(
                    f"| `{key}` | {_type(schema)} | {_default(key, schema, required)} | "
                    f"{notes['params'].get(key, '')} |"
                )
        else:
            lines.append("No parameters.")
        lines += [
            "",
            f"**Returns:** {notes['returns']}",
            "",
            f"**Source:** {notes['source']}. **Licence:** {notes['licence']}.",
            "",
            "**Caveats:**",
            *[f"- {caveat}" for caveat in notes["caveats"]],
        ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "TOOLS.md"
    target.write_text(asyncio.run(build()), encoding="utf-8")
    print(f"Wrote {target}")
