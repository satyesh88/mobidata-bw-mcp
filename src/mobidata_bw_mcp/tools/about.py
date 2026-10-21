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
            "EFA-BW TRIAS departures and journey planning (requires configured access)",
            "MobiData BW roadworks and traffic-sign GeoJSON exports",
            "MobiData BW traffic messages (DATEX II)",
            "OpenStreetMap Nominatim geocoding",
        ],
        "licences": (
            "Project: PolyForm Noncommercial 1.0.0; commercial use outside its permissions "
            "requires a separate written licence from Satyesh Shivam (RouteIQ). "
            "Earlier Apache-2.0 releases retain their original rights. "
            "Data licences vary by dataset; each result includes source and attribution."
        ),
        "caveats": [
            "GTFS departures are scheduled. TRIAS predictions depend on operator coverage; "
            "missing live data never confirms on-time running.",
            "BFRK surveys may be outdated, coordinates are offset 1.5-4 m, "
            "and elevator details are not live status.",
            "Traffic-sign results are not legally binding and omit supplementary signs.",
            "This independent project is not affiliated with or endorsed by NVBW.",
        ],
        "contact": "Satyesh Shivam (RouteIQ)",
    }