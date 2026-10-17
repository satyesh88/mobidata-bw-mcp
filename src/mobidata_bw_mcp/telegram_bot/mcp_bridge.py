import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent, Tool


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


def tool_error_result(name: str) -> CallToolResult:
    message = (
        "The accessibility lookup failed"
        if name in {"find_accessible_parking", "stop_accessibility"}
        else "The mobility lookup failed"
    )
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps({"error": True, "message": message}),
            )
        ],
        isError=True,
    )


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
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mobidata_bw_mcp.server"],
        )
        try:
            async with (
                stdio_client(parameters) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                self.tools = anthropic_tools(listed.tools)
                self._ready.set()
                while request := await self._queue.get():
                    try:
                        result = await session.call_tool(request.name, request.arguments)
                    except Exception:
                        if not request.future.done():
                            request.future.set_result(tool_error_result(request.name))
                    else:
                        if not request.future.done():
                            request.future.set_result(result)
        except BaseException as exc:
            if not self._ready.is_set():
                self._startup_error = exc
                self._ready.set()
            else:
                self._fail_pending(exc)
                raise

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