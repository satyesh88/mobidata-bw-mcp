"""Europe/Berlin time handling for the bot. Every tool result and every reply goes through here."""

import json
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$"
)
_UTC_CLOCK = re.compile(
    r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?\s*(?:Uhr\s*)?(?:UTC|GMT)\b", re.IGNORECASE
)


def berlin_iso(value: str) -> str:
    """Timezone-aware ISO timestamp as Europe/Berlin local time; anything else is unchanged."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(BERLIN).isoformat(timespec="seconds")


def localize_value(value: Any) -> Any:
    if isinstance(value, str):
        return berlin_iso(value) if _ISO_TIMESTAMP.match(value) else value
    if isinstance(value, list):
        return [localize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: localize_value(item) for key, item in value.items()}
    return value


def localize_tool_result(text: str) -> str:
    """The single place where tool results get Berlin timestamps, whatever the tool."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return text
    return json.dumps(localize_value(value), ensure_ascii=False, default=str)


def localize_clock_text(text: str, now: datetime) -> str:
    """Safety net: rewrite a model-written 'HH:MM UTC' to Berlin HH:MM, using today's UTC date."""
    today = now.astimezone(UTC).date()

    def convert(match: re.Match[str]) -> str:
        utc = datetime(
            today.year, today.month, today.day, int(match.group(1)), int(match.group(2)), tzinfo=UTC
        )
        return utc.astimezone(BERLIN).strftime("%H:%M")

    return _UTC_CLOCK.sub(convert, text)
