import re
from pathlib import Path

import pytest

from mobidata_bw_mcp.server import mcp

SKILL = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"


def test_skill_has_valid_frontmatter_and_stays_short() -> None:
    text = SKILL.read_text(encoding="utf-8")
    match = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", text)

    assert match, "SKILL.md needs name and description frontmatter"
    assert match.group(1) == "mobidata-bw"
    assert len(match.group(2)) <= 1024
    assert len(text.splitlines()) < 300


@pytest.mark.asyncio
async def test_skill_mentions_every_server_tool() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [tool.name for tool in await mcp.list_tools() if f"`{tool.name}`" not in text]

    assert missing == [], f"SKILL.md does not cover: {missing}"


def test_skill_keeps_the_route_and_safety_rules() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "always call check_route" in text
    assert "Never answer a route-between-places question using only get_roadworks" in text
    assert "not legally binding" in text
    assert "survey year" in text
    assert "has already passed" in text
    assert "do not silently use next year" in text
    assert "never write \"UTC\"" in text
    assert "Daten: MobiData BW® / NVBW und Datengeber" in text
