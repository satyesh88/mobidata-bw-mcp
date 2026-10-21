"""Render transit facts from structured data, independently of model wording."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
PHONE_DEPARTURES = 8


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def time_label(item: dict, german: bool = False) -> str:
    planned = _datetime(item.get("scheduled_time")) or _datetime(item.get("departure"))
    predicted = _datetime(item.get("estimated_time"))
    if planned is None:
        return "Fahrplanzeit fehlt" if german else "scheduled time not reported"
    label = ("planmäßig " if german else "scheduled ") + planned.astimezone(BERLIN).strftime(
        "%H:%M"
    )
    if predicted is None:
        return label + (" — keine Echtzeitprognose" if german else " — no live prediction")
    delay = round((predicted - planned).total_seconds() / 60, 1)
    if delay == 0:
        return label + (" — pünktlich" if german else " — on time")
    clock = predicted.astimezone(BERLIN).strftime("%H:%M")
    return label + f" — {'erw.' if german else 'est.'} {clock} ({delay:+g} min)"


def render_departures(
    data: dict, offset: int = 0, german: bool = False, accessibility: bool = False
) -> tuple[str, int]:
    items = data.get("items", [])
    page = items[offset : offset + PHONE_DEPARTURES]
    lines = ["Abfahrten" if german else "Departures"]
    for item in page:
        parts = [
            time_label(item, german),
            str(item.get("route") or "?"),
            str(item.get("headsign") or ("Ziel unbekannt" if german else "destination unknown")),
        ]
        if item.get("stop_name"):
            parts.append(str(item["stop_name"]))
        if item.get("platform"):
            parts.append(f"{'Gleis' if german else 'platform'} {item['platform']}")
        if item.get("cancelled"):
            parts.append("fällt aus" if german else "cancelled")
        if accessibility:
            status = item.get("wheelchair_accessible", "unknown")
            parts.append(
                {
                    "accessible": "barrierefrei" if german else "accessible",
                    "not_accessible": "nicht barrierefrei" if german else "not accessible",
                }.get(
                    status,
                    "keine Barrierefreiheitsinfo im Fahrplan"
                    if german
                    else "no accessibility info in the timetable",
                )
            )
        lines.append(" · ".join(parts))
    end = offset + len(page)
    more = end < len(items) or data.get("next_cursor") is not None
    summary = f"{len(page)} Abfahrten angezeigt." if german else f"{len(page)} departures shown."
    if more:
        summary += " Mehr?" if german else " More?"
    lines.append(summary)
    query = data.get("query", {})
    if query.get("realtime_status"):
        lines.append(
            "Nur Fahrplan; Echtzeitdaten nicht verfügbar."
            if german
            else "Scheduled timetable only; live data unavailable."
        )
    if not data.get("window_complete", True) and not more:
        lines.append(
            "Weitere Abfahrten konnten nicht geprüft werden."
            if german
            else "Further departures could not be verified; please try again."
        )
    return "\n".join(lines), end


def render_journeys(data: dict, german: bool = False) -> str:
    lines = []
    for index, item in enumerate(data.get("items", [])[:3], 1):
        transfers = item.get("transfers", 0)
        transfer_label = (
            ("direkt" if german else "direct")
            if not transfers
            else (
                f"{transfers} Umstieg(e)"
                if german
                else f"{transfers} change{'s' if transfers != 1 else ''}"
            )
        )
        lines.append(
            f"{index}. {transfer_label}" + (" — cancelled" if item.get("cancelled") else "")
        )
        for leg in item.get("legs", []):
            if leg.get("kind") != "public_transport":
                if leg.get("duration"):
                    lines.append(f"{'Fußweg' if german else 'Walk/access'}: {leg['duration']}")
                continue
            board, alight = leg.get("board", {}), leg.get("alight", {})
            source, target = board.get("platform"), alight.get("platform")
            platforms = (
                f"Abfahrt Gleis {source or '?'}, Ankunft Gleis {target or '?'}"
                if german
                else f"departs platform {source or '?'}, arrives platform {target or '?'}"
            )
            lines.append(
                f"{leg.get('route', '?')}: {time_label(board, german)} → "
                f"{time_label(alight, german)}; {platforms}"
            )
        if item.get("accessibility_preferences_requested"):
            lines.append(
                "Barrierefreiheit angefragt, nicht bestätigt; Liftstatus unbekannt."
                if german
                else "Accessibility requested, not verified; lift operation unknown."
            )
    return "\n".join(lines)
