import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent, Tool

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def server_url() -> str | None:
    """Hosted MCP endpoint from MCP_SERVER_URL; plain HTTP is only allowed on loopback."""
    url = os.getenv("MCP_SERVER_URL", "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS):
        return url
    raise RuntimeError("MCP_SERVER_URL must use https, or http on loopback")


@asynccontextmanager
async def open_streams(url: str | None) -> AsyncIterator[tuple[Any, Any]]:
    if url:
        key = os.getenv("MCP_SERVER_KEY", "").strip()
        headers = {"Authorization": f"Bearer {key}"} if key else None
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            yield read, write
    else:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mobidata_bw_mcp.server"],
        )
        async with stdio_client(parameters) as (read, write):
            yield read, write


def anthropic_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic's tool schema."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        for tool in tools
    ]


def result_text(result: CallToolResult) -> str:
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent, ensure_ascii=False, default=str)

    parts = []
    for item in result.content:
        if isinstance(item, TextContent):
            parts.append(item.text)
        else:
            parts.append(item.model_dump_json(exclude_none=True))
    return "\n".join(parts)


def tool_failure_message(name: str) -> str:
    subject = {
        "find_parking": "parking", "find_accessible_parking": "accessible parking",
        "stop_accessibility": "station accessibility", "find_charging": "charging",
        "find_sharing": "sharing", "find_transit": "nearby stops",
        "get_departures": "timetable", "get_roadworks": "roadworks",
        "check_route": "route", "find_traffic_signs": "traffic signs",
        "find_traffic_messages": "traffic messages", "data_health": "data freshness",
        "search_datasets": "dataset search", "get_dataset": "dataset metadata",
        "list_layers": "map layers", "query_layer": "map data", "about": "server information",
    }.get(name, "requested source")
    return (f"I couldn’t retrieve {subject} data; please try again shortly "
            "or send a more specific place or street and city.")


def tool_error_result(name: str, error: Exception | None = None) -> CallToolResult:
    logging.getLogger(__name__).warning(
        "The mobility lookup failed tool=%s error=%s", name,
        type(error).__name__ if error else "tool_error",
    )
    # Only our structured clarification is safe to expose; never forward arbitrary exceptions.
    from ..clients.geocode import LocationClarification

    message = str(error) if isinstance(error, LocationClarification) else json.dumps({
        "error": True, "message": tool_failure_message(name),
    })
    return CallToolResult(content=[TextContent(type="text", text=message)], isError=True)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    future: asyncio.Future[CallToolResult]


class MCPBridge:
    """Own one MCP server process and one persistent client session."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self._queue: asyncio.Queue[ToolCall | None] = asyncio.Queue()
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._startup_error: BaseException | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="mobidata-mcp-bridge")
        await self._ready.wait()
        if self._startup_error is not None:
            await self._task
            self._task = None
            raise RuntimeError("Could not start the MobiData MCP server") from self._startup_error

    async def close(self) -> None:
        if self._task is None:
            return
        if not self._task.done():
            await self._queue.put(None)
        try:
            await self._task
        finally:
            self._task = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._task is None or self._task.done():
            raise RuntimeError("MCP bridge is not running")
        future = asyncio.get_running_loop().create_future()
        await self._queue.put(ToolCall(name, arguments, future))
        return await future

    async def _run(self) -> None:
        try:
            async with (
                open_streams(server_url()) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                self.tools = anthropic_tools(listed.tools)
                self._ready.set()
                # ClientSession multiplexes requests by ID with separate response streams.
                # Keep stream/session ownership here while dispatching calls concurrently.
                async with asyncio.TaskGroup() as group:
                    while request := await self._queue.get():
                        group.create_task(self._dispatch(session, request))
        except BaseException as exc:
            if not self._ready.is_set():
                self._startup_error = exc
                self._ready.set()
            else:
                self._fail_pending(exc)
                raise

    async def _dispatch(self, session: ClientSession, request: ToolCall) -> None:
        if request.future.done():
            return

        async def invoke() -> CallToolResult:
            try:
                async with asyncio.timeout(15):
                    return await session.call_tool(request.name, request.arguments)
            except TimeoutError:
                return CallToolResult(
                    content=[], isError=True,
                    structuredContent={
                        "error": ("source_timeout" if request.name == "get_departures"
                                  else "source timed out"),
                        "tool": request.name, "partial": True
                    },
                )
            except Exception as error:
                return tool_error_result(request.name, error)

        task = asyncio.create_task(invoke())
        request.future.add_done_callback(lambda _: task.cancel() if not task.done() else None)
        try:
            result = await task
            if not request.future.done():
                request.future.set_result(result)
        except asyncio.CancelledError:
            if not request.future.done():
                request.future.cancel()

    def _fail_pending(self, error: BaseException) -> None:
        while not self._queue.empty():
            request = self._queue.get_nowait()
            if request is not None and not request.future.done():
                request.future.set_exception(error)

    async def __aenter__(self) -> "MCPBridge":
        await self.start()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()
