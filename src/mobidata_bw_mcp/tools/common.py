from datetime import UTC, datetime
from typing import Any

from ..config import settings


def limit_value(limit: int) -> int:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return min(limit, settings.max_limit)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def freshness(
    timestamp: str | None,
    *,
    outdated: bool | None = None,
    live_available: bool = True,
) -> dict[str, Any]:
    parsed = parse_timestamp(timestamp)
    age = None
    if parsed:
        age = max(0.0, (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() / 60)
    is_live = live_available and outdated is not True and (age is None or age <= 30)
    return {
        "is_live": is_live,
        "age_minutes": round(age, 1) if age is not None else None,
        "updated_at": timestamp,
    }


def latest_datetime(values: list[str | None]) -> datetime | None:
    parsed = [item for value in values if (item := parse_timestamp(value))]
    return max(parsed) if parsed else None