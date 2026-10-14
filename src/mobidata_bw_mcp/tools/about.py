from typing import Any

from .. import __version__


def about() -> dict[str, Any]:
    """Describe this server, its source systems, licences, and important usage caveats."""
    return {
        "name": "MobiData BW MCP Server",
        "version": __version__,
        "description": "One agent interface over public MobiData BW mobility APIs.",
        "sources": [
            "MobiData BW CKAN catalogue",
            "MobiData BW GeoServer WFS",
            "ParkAPI v3",
            "BFRK accessibility surveys for Baden-Württemberg stops and stations",
            "GTFS PostgREST",
            "MobiData BW roadworks and traffic-sign GeoJSON exports",
            "OpenStreetMap Nominatim geocoding",
        ],
        "licences": "Vary by dataset; each result includes source and attribution.",
        "caveats": [
            "Scheduled public transport only; no GTFS realtime data.",
            "BFRK surveys may be outdated, coordinates are offset 1.5-4 m, "
            "and elevator details are not live status.",
            "Traffic-sign results are not legally binding and omit supplementary signs.",
            "This independent project is not affiliated with or endorsed by NVBW.",
        ],
        "contact": "Satyesh Shivam (RouteIQ)",
    }