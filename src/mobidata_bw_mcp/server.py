import argparse
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .models import BBox, LocationInput, RoutePoint, Vehicle
from .tools import (
    accessibility,
    charging,
    discovery,
    health,
    parking,
    roadworks,
    route_check,
    sharing,
    signs,
    spatial,
    traffic_messages,
    transit,
)
from .tools.about import about as about_data


@asynccontextmanager
async def lifespan(_server: FastMCP):
    await signs.sign_index()
    yield


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    stateless_http: bool = False,
    transport_security: TransportSecuritySettings | None = None,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> FastMCP:
    mcp = FastMCP(
        "MobiData BW",
        instructions=(
            "Use opinionated find_* tools for mobility questions. Report source, licence, "
            "timestamp, freshness, and warnings from every result. Traffic-sign data is advisory."
        ),
        host=host,
        port=port,
        stateless_http=stateless_http,
        transport_security=transport_security,
        log_level=log_level,
        lifespan=None if stateless_http else lifespan,
    )

    mcp.tool()(discovery.search_datasets)
    mcp.tool()(discovery.get_dataset)
    mcp.tool()(discovery.list_layers)
    mcp.tool()(spatial.query_layer)
    mcp.tool()(parking.find_parking)
    mcp.tool()(accessibility.find_accessible_parking)
    mcp.tool()(accessibility.stop_accessibility)
    mcp.tool()(charging.find_charging)
    mcp.tool()(sharing.find_sharing)
    mcp.tool()(transit.find_transit)

    @mcp.tool()
    async def get_departures(
        stop_or_station_id: str,
        date: date | None = None,
        from_time: datetime | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get scheduled departures; dates near today may not be published yet."""
        return await transit.get_departures(stop_or_station_id, date, from_time, limit)

    @mcp.tool()
    async def get_roadworks(
        location: LocationInput | dict[str, Any] | None = None,
        bbox: BBox | dict[str, Any] | None = None,
        radius_m: int = 5000,
        active_on: date | None = None,
        active_from: date | None = None,
        active_to: date | None = None,
    ) -> dict[str, Any]:
        """Find roadworks active on a date or during any day in a date range."""
        return await roadworks.get_roadworks(
            location, bbox, radius_m, active_on, active_from, active_to
        )

    mcp.tool()(signs.find_traffic_signs)
    mcp.tool()(traffic_messages.find_traffic_messages)

    @mcp.tool()
    async def check_route(
        route: dict[str, Any] | list[RoutePoint],
        buffer_m: int = 30,
        date: date | None = None,
        vehicle: Vehicle | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check a route for roadworks, traffic messages, and advisory truck signs."""
        return await route_check.check_route(route, buffer_m, date, vehicle)

    mcp.tool()(health.data_health)

    @mcp.tool()
    def about() -> dict[str, Any]:
        """Describe this server, its source systems, licences, and important caveats."""
        return about_data()

    @mcp.resource("mobidata://about")
    def about_resource() -> dict[str, Any]:
        """Server metadata, source systems, licences, and caveats."""
        return about_data()

    return mcp


mcp = create_server()


def main() -> None:
    parser = argparse.ArgumentParser(description="MobiData BW MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http", "streamable-http"),
        default="stdio",
        help="stdio (default) or hosted streamable HTTP at /mcp with API-key auth",
    )
    parser.add_argument("--host", default=os.getenv("MOBIDATA_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MOBIDATA_MCP_PORT", "8000")))
    parser.add_argument(
        "--insecure-no-auth",
        action="store_true",
        help="HTTP without API keys. For local testing only.",
    )
    args = parser.parse_args()
    if args.transport == "stdio":
        create_server().run(transport="stdio")
    else:
        from .http_app import serve

        serve(args.host, args.port, args.insecure_no_auth)


if __name__ == "__main__":
    main()