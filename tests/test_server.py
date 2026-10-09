import pytest

from mobidata_bw_mcp.server import mcp


@pytest.mark.asyncio
async def test_server_exposes_expected_tools_and_parameters() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert len(tools) == 14
    assert {"date", "route", "buffer_m", "vehicle"} == set(
        tools["check_route"].inputSchema["properties"]
    )
    assert "date" in tools["get_departures"].inputSchema["properties"]
    assert "active_on" in tools["get_roadworks"].inputSchema["properties"]


@pytest.mark.asyncio
async def test_about_resource_is_registered() -> None:
    resources = await mcp.list_resources()
    assert any(str(resource.uri) == "mobidata://about" for resource in resources)


@pytest.mark.asyncio
async def test_about_can_be_called_through_mcp_dispatcher() -> None:
    content, structured = await mcp.call_tool("about", {})

    assert content[0].type == "text"
    assert structured["name"] == "MobiData BW MCP Server"