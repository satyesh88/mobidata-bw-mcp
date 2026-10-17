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
    assert len(text.splitlines()) < 500


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n"), "SKILL.md must start with frontmatter"
    block = text.split("\n---\n", 1)[0].removeprefix("---\n")
    fields: dict[str, str] = {}
    for line in block.splitlines():
        key, separator, value = line.partition(": ")
        assert separator, f"frontmatter line is not 'key: value': {line!r}"
        fields[key] = value
    return fields


def test_skill_description_is_valid_and_triggers_without_a_slash_command() -> None:
    fields = _frontmatter(SKILL.read_text(encoding="utf-8"))
    description = fields["description"]

    assert fields["name"] == "mobidata-bw"
    assert len(description) <= 1024
    assert "<" not in description and ">" not in description
    assert ": " not in description, "a colon would break the YAML plain scalar"
    assert description.endswith(
        "Use whenever the MobiData BW MCP tools are available and the question involves a "
        "place or route in Baden-Württemberg."
    )
    for trigger in (
        "Baden-Württemberg", "Stuttgart", "Heilbronn", "Karlsruhe", "Freiburg", "Mannheim",
        "Ulm", "Hbf", "Bahnhof", "parking", "Parkhaus", "charging", "Ladesäule", "e-scooter",
        "bike sharing", "car sharing", "departures", "step-free", "barrierefrei", "wheelchair",
        "lifts", "roadworks", "Baustelle", "closures", "truck", "LKW", "traffic signs",
        "open data catalogue",
    ):
        assert trigger in description, f"description lacks the trigger {trigger!r}"


def test_skill_sets_the_answer_length_by_channel_and_keeps_the_honesty_rules() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "Chat apps (Telegram, WhatsApp, SMS-like)" in text
    assert "At most about five short lines" in text
    assert "Desktop, web and IDE chats (the default)" in text
    assert "Searched around:" in text
    assert "Never show raw internal IDs" in text
    assert "Never guess a track" in text
    assert "Never refer to items that are not in the answer" in text
    assert "Only compare with data from the current tool results" in text
    assert "was not recorded" in text
    assert "## Worked examples" in text
    assert "Desktop answer" in text and "Telegram answer" in text


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
