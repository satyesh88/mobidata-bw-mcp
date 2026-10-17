import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from ..geo import haversine_m
from .mcp_bridge import MCPBridge, result_text, tool_error_result
from .timefmt import localize_clock_text, localize_tool_result

OFF_TOPIC_MARKER = "[[OFF_TOPIC]]"
_SKILL_PATH = Path(__file__).resolve().parents[3] / "skill" / "SKILL.md"


def _skill_rules() -> str:
    """Domain rules live in the published skill so the bot and other agents share one source."""
    text = _SKILL_PATH.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


SYSTEM_PROMPT = f"""You are the MobiData BW Assistant, a concise mobility assistant.
Answer only questions about mobility in Baden-Württemberg using the provided tools. For any
other topic reply with exactly {OFF_TOPIC_MARKER} and nothing else; the application declines.

{_skill_rules()}

Telegram channel rules (these override anything above):
- Use at most five short phone-sized lines, no tables, sparse relevant emoji. A list the user
  explicitly asked for, such as all datasets of a category, may be longer: one short line per item.
- Do not write the "Searched around" line yourself; the application adds it.
- Never mention tool names or internal implementation.
- All times are Europe/Berlin local time, written HH:MM. Tool timestamps are already converted;
  never write UTC or Z.
- Name each recommended place exactly as the data names it; if that name is generic (for example
  "Parkplatz"), use its street instead. Put your best recommendation first, then the others in the
  order you recommend them.
- If the context note says a date has already passed, the application writes the first line of the
  answer about it. Do not write that line yourself.
- End every answer with exactly this line:
Daten: MobiData BW® / NVBW und Datengeber
- Do not append corrections or commentary about earlier answers unless the current question
  explicitly asks for a correction or comparison.
"""

FINAL_PROMPT = "Answer now with the data you have. Do not call tools."
USE_TOOLS_PROMPT = (
    "Use the tools before answering. Do not state unverified facts. "
    f"If this is off-topic, reply with exactly {OFF_TOPIC_MARKER}."
)
EMPTY_ANSWER = "Sorry, I couldn’t produce an answer from the available data. Please try again."
OFF_TOPIC_EN = "Sorry, I can only help with mobility questions."
OFF_TOPIC_DE = "Entschuldigung, ich kann nur bei Mobilitätsfragen helfen."
ACCESSIBILITY_ERROR = "The accessibility lookup failed"
MOBILITY_ERROR = "The mobility lookup failed"
_FACT_PATTERN = re.compile(
    r"\d|\b(?:in|near|around|at|bei|nahe|um|am)\s+[A-ZÄÖÜ][\wÄÖÜäöüß-]+"
)
_PLACE_PATTERN = re.compile(r"\b[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)*\b")
_NON_PLACE_WORDS = {
    "Answer",
    "Bitte",
    "Could",
    "Daten",
    "Das",
    "Der",
    "Die",
    "I",
    "Ich",
    "MobiData",
    "No",
    "Please",
    "Sorry",
}
_GERMAN_PATTERN = re.compile(
    r"\b(?:ich|mir|mich|hier|nähe|parkplatz|baustelle|lade|gibt|sind|ist|um)\b",
    re.IGNORECASE,
)
_MOBILITY_PATTERN = re.compile(
    r"\b(?:bus|train|transit|parking|parkplatz|laden|charger|charging|scooter|"
    r"bike|bicycle|road|route|truck|traffic|sign|baustelle|verkehr|straße|zug|bahn)\w*\b",
    re.IGNORECASE,
)
_CORRECTION_REQUEST_PATTERN = re.compile(
    r"\b(?:correct|correction|earlier|previous|before|korrigier|korrektur|zuvor|vorher)\b",
    re.IGNORECASE,
)
_CORRECTION_LINE_PATTERN = re.compile(
    r"^(?:correction|earlier|previously|about my earlier answer|"
    r"korrektur|zuvor|zu meiner vorherigen antwort)\b.*$",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1,
    "januar": 1,
    "jan": 1,
    "february": 2,
    "februar": 2,
    "feb": 2,
    "march": 3,
    "märz": 3,
    "maerz": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "mai": 5,
    "june": 6,
    "juni": 6,
    "jun": 6,
    "july": 7,
    "juli": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oktober": 10,
    "oct": 10,
    "okt": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dezember": 12,
    "dec": 12,
    "dez": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NO_YEAR_AFTER = r"(?!\.?,?\s*\d{4})"
_DAY_FIRST_DATE = re.compile(
    rf"\b(\d{{1,2}})\.?\s+({_MONTH_NAMES})\b{_NO_YEAR_AFTER}", re.IGNORECASE
)
_MONTH_FIRST_DATE = re.compile(
    rf"\b({_MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?![:.]?\d){_NO_YEAR_AFTER}",
    re.IGNORECASE,
)


@dataclass
class RecommendedPlace:
    name: str
    lat: float
    lon: float
    kind: str
    address: str
    street: str | None = None


@dataclass
class AgentAnswer:
    text: str
    input_tokens: int
    output_tokens: int
    tools_used: list[str]
    stop_reason: str | None
    tool_rounds: int
    places: list[RecommendedPlace]
    off_topic: bool = False


class MobilityAgent:
    def __init__(
        self,
        bridge: MCPBridge,
        model: str,
        max_tool_rounds: int = 10,
        workspace_id: str | None = None,
    ) -> None:
        self.bridge = bridge
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        default_headers = (
            {"anthropic-workspace-id": workspace_id} if workspace_id else None
        )
        self.client = AsyncAnthropic(default_headers=default_headers)

    async def answer(
        self,
        question: str,
        history: list[dict[str, str]],
        location: tuple[float, float] | None = None,
    ) -> AgentAnswer:
        request_time = _berlin_now()
        system_prompt = _system_prompt(request_time)
        messages: list[dict[str, Any]] = [*history]
        prompt = question
        date_line = _passed_date_line(question, request_time)
        date_context = _yearless_date_context(question, request_time)
        if date_context:
            prompt += f"\n\n{date_context}"
        prompt += (
            "\n\nReply in German because the current message is German."
            if _GERMAN_PATTERN.search(question)
            else "\n\nReply in English because the current message is English."
        )
        if location is not None:
            latitude, longitude = location
            prompt += (
                "\n\nThe user shared this current location (valid for this question): "
                f"latitude {latitude}, longitude {longitude}."
            )
        messages.append({"role": "user", "content": prompt})

        input_tokens = 0
        output_tokens = 0
        tools_used: list[str] = []
        recommended_places: list[RecommendedPlace] = []
        searched_place: tuple[str, str | None] | None = (
            ("shared Telegram location", "coordinates") if location is not None else None
        )
        tool_rounds = 0
        stop_reason: str | None = None
        grounding_retry = False
        off_topic = False
        tool_error_text: str | None = None
        for _round in range(self.max_tool_rounds + 1):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=system_prompt,
                messages=messages,
                tools=self.bridge.tools,
            )
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            stop_reason = response.stop_reason
            text = "\n".join(
                block.text for block in response.content if block.type == "text"
            ).strip()
            tool_blocks = [block for block in response.content if block.type == "tool_use"]
            if not tool_blocks:
                if not text or response.stop_reason == "max_tokens":
                    if response.content:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": [
                                    block.model_dump(mode="json")
                                    for block in response.content
                                ],
                            }
                        )
                    break
                if not tools_used and _is_decline(text):
                    return AgentAnswer(
                        _off_topic_reply(question),
                        input_tokens,
                        output_tokens,
                        tools_used,
                        stop_reason,
                        tool_rounds,
                        [],
                        off_topic=True,
                    )
                if not tools_used and _looks_factual(text):
                    if not grounding_retry:
                        messages.extend(
                            [
                                {
                                    "role": "assistant",
                                    "content": [
                                        block.model_dump(mode="json")
                                        for block in response.content
                                    ],
                                },
                                {"role": "user", "content": USE_TOOLS_PROMPT},
                            ]
                        )
                        grounding_retry = True
                        continue
                    text, off_topic = _ungrounded_reply(question)
                final_text = _finish_text(
                    text,
                    question,
                    request_time,
                    tool_error_text,
                    searched_place,
                    date_line if tools_used else None,
                )
                return AgentAnswer(
                    final_text,
                    input_tokens,
                    output_tokens,
                    tools_used,
                    stop_reason,
                    tool_rounds,
                    _places_for_answer(final_text, recommended_places),
                    off_topic=off_topic,
                )
            if _round >= self.max_tool_rounds:
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": [block.model_dump(mode="json") for block in response.content],
                }
            )
            tool_results = []
            for block in tool_blocks:
                tools_used.append(block.name)
                try:
                    result = await self.bridge.call_tool(block.name, block.input)
                except Exception:
                    result = tool_error_result(block.name)
                serialized_result = result_text(result)
                if result.isError:
                    tool_error_text = (
                        ACCESSIBILITY_ERROR
                        if block.name
                        in {"find_accessible_parking", "stop_accessibility"}
                        else MOBILITY_ERROR
                    )
                    serialized_result = result_text(tool_error_result(block.name))
                else:
                    serialized_result = localize_tool_result(serialized_result)
                    searched_place = searched_place or _resolved_place(serialized_result)
                    recommended_places = _merge_places(
                        recommended_places,
                        _recommended_places(serialized_result, block.name, block.input),
                    )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _model_result_text(
                            serialized_result, _item_limit(block.name)
                        )[:8000],
                        "is_error": bool(result.isError),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            tool_rounds += 1

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=system_prompt,
            messages=[*messages, {"role": "user", "content": FINAL_PROMPT}],
        )
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens
        stop_reason = response.stop_reason
        text = "\n".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if not tools_used and _is_decline(text):
            text, off_topic = _off_topic_reply(question), True
        elif not tools_used and _looks_factual(text):
            text, off_topic = _ungrounded_reply(question)
        final_text = _finish_text(
            text,
            question,
            request_time,
            tool_error_text,
            searched_place,
            date_line if tools_used else None,
        )
        return AgentAnswer(
            final_text,
            input_tokens,
            output_tokens,
            tools_used,
            stop_reason,
            tool_rounds,
            _places_for_answer(final_text, recommended_places),
            off_topic=off_topic,
        )


def _looks_factual(text: str) -> bool:
    body = text.replace("Daten: MobiData BW® / NVBW und Datengeber", "")
    if _FACT_PATTERN.search(body):
        return True
    return any(word not in _NON_PLACE_WORDS for word in _PLACE_PATTERN.findall(body))


def _berlin_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Berlin"))


def _system_prompt(now: datetime) -> str:
    timestamp = now.isoformat(timespec="seconds")
    return (
        f"{SYSTEM_PROMPT}\nCurrent Europe/Berlin date and time: {timestamp}.\n"
        "A date without a year means that day this year. If it has already passed, do not use "
        "next year: use today's date instead, as the context note says."
    )


@dataclass(frozen=True)
class YearlessDate:
    typed: str
    day: int
    month_word: str
    occurrence: date
    passed: bool


def _yearless_dates(question: str, now: datetime) -> list[YearlessDate]:
    found: list[tuple[int, str, int, str]] = []
    for match in _DAY_FIRST_DATE.finditer(question):
        found.append((match.start(), match.group(0), int(match.group(1)), match.group(2)))
    for match in _MONTH_FIRST_DATE.finditer(question):
        found.append((match.start(), match.group(0), int(match.group(2)), match.group(1)))
    dates = []
    for _position, typed, day, month_word in sorted(found):
        try:
            occurrence = date(now.year, _MONTHS[month_word.casefold()], day)
        except ValueError:
            continue
        dates.append(
            YearlessDate(typed, day, month_word, occurrence, occurrence < now.date())
        )
    return dates


def _yearless_date_context(question: str, now: datetime) -> str | None:
    dates = _yearless_dates(question, now)
    if not dates:
        return None
    notes = []
    upcoming = [f"{d.typed} = {d.occurrence.isoformat()}" for d in dates if not d.passed]
    if upcoming:
        notes.append("Resolved yearless dates (this year): " + "; ".join(upcoming))
    for passed in (d for d in dates if d.passed):
        notes.append(
            f"{passed.typed} has already passed this year ({passed.occurrence.isoformat()}). "
            f"Do not use next year. Use today's date {now.date().isoformat()} for the tool "
            "calls. The application writes the first line of the answer about this."
        )
    return "\n".join(notes)


def _passed_date_line(question: str, now: datetime) -> str | None:
    """First reply line when the user named a day this year that is already over."""
    passed = next((d for d in _yearless_dates(question, now) if d.passed), None)
    if passed is None:
        return None
    next_year = now.year + 1
    if _GERMAN_PATTERN.search(question):
        label = f"{passed.day}. {passed.month_word}"
        return (
            f"Der {label} ist vorbei. Ich zeige die heutige Lage. "
            f"Meinten Sie den {label} {next_year}?"
        )
    label = f"{passed.day} {passed.month_word}"
    return f"{label} has passed. Showing today's situation. Did you mean {label} {next_year}?"


def _finish_text(
    text: str,
    question: str,
    request_time: datetime,
    tool_error_text: str | None,
    searched_place: tuple[str, str | None] | None,
    date_line: str | None,
) -> str:
    final_text = _without_unsolicited_corrections(text or EMPTY_ANSWER, question)
    final_text = localize_clock_text(final_text, request_time)
    if tool_error_text is not None:
        return tool_error_text
    if searched_place is not None:
        final_text = _with_searched_place(final_text, searched_place, question)
    if date_line:
        final_text = f"{date_line}\n{final_text}"
    return final_text


_DECLINE_PATTERN = re.compile(
    r"\b(?:can only (?:help|answer)|only (?:help|answer)|kann nur|nur bei mobilit|nur fragen)",
    re.IGNORECASE,
)


def _is_decline(text: str) -> bool:
    return OFF_TOPIC_MARKER in text or _DECLINE_PATTERN.search(text) is not None


def _off_topic_reply(question: str) -> str:
    return OFF_TOPIC_DE if _GERMAN_PATTERN.search(question) else OFF_TOPIC_EN


def _ungrounded_reply(question: str) -> tuple[str, bool]:
    """Reply used when the model stated facts without a tool call; True means off-topic."""
    if _MOBILITY_PATTERN.search(question):
        return EMPTY_ANSWER, False
    return _off_topic_reply(question), True


def _without_unsolicited_corrections(text: str, question: str) -> str:
    if _CORRECTION_REQUEST_PATTERN.search(question):
        return text
    lines = [
        line
        for line in text.splitlines()
        if not _CORRECTION_LINE_PATTERN.match(line.strip())
    ]
    return "\n".join(lines).strip() or EMPTY_ANSWER


def _resolved_place(text: str) -> tuple[str, str | None] | None:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None

    def find(item: Any) -> tuple[str, str | None] | None:
        if isinstance(item, dict):
            query = item.get("query")
            if isinstance(query, dict) and isinstance(query.get("location"), dict):
                location = query["location"]
                if location.get("label"):
                    return str(location["label"]), location.get("type")
            for nested in item.values():
                found = find(nested)
                if found:
                    return found
        elif isinstance(item, list):
            for nested in item:
                found = find(nested)
                if found:
                    return found
        return None

    return find(value)


_PLACE_TOOLS = {
    "find_parking",
    "find_accessible_parking",
    "find_charging",
    "find_sharing",
    "stop_accessibility",
    "find_transit",
}


def _recommended_places(
    text: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> list[RecommendedPlace]:
    if tool_name not in _PLACE_TOOLS:
        return []
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict):
        return []
    query = value.get("query")
    query_location = query.get("location") if isinstance(query, dict) else None
    fallback_address = (
        str(query_location.get("label"))
        if isinstance(query_location, dict) and query_location.get("label")
        else "Location from MobiData BW"
    )
    places: list[RecommendedPlace] = []
    for item in value.get("items", []):
        if not isinstance(item, dict) or item.get("lat") is None or item.get("lon") is None:
            continue
        kind = _place_kind(tool_name, item, arguments or {})
        name = item.get("name") or item.get("station_name") or _default_place_name(kind)
        address = _address_text(item.get("address")) or item.get("city") or fallback_address
        places.append(
            RecommendedPlace(
                name=str(name),
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                kind=kind,
                address=str(address),
                street=_street_text(item.get("address")),
            )
        )
        if len(places) == 20:
            break
    return places


def _place_kind(
    tool_name: str, item: dict[str, Any], arguments: dict[str, Any]
) -> str:
    if tool_name in {"find_parking", "find_accessible_parking"}:
        if str(arguments.get("purpose", "")).upper() == "BIKE":
            return "bike_parking"
        accessibility = f"{arguments.get('purpose', '')} {item.get('type', '')}".casefold()
        return (
            "accessible_parking"
            if any(
                marker in accessibility
                for marker in ("accessib", "disabled", "handicap", "wheelchair")
            )
            else "parking"
        )
    if tool_name == "find_charging":
        return "charger"
    if tool_name in {"find_transit", "stop_accessibility"}:
        return "station"
    return str(item.get("kind") or item.get("item_type") or "sharing")


def _address_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    parts = [
        value.get("street") or value.get("road"),
        value.get("house_number") or value.get("housenumber"),
        value.get("postal_code") or value.get("postcode"),
        value.get("city") or value.get("town"),
    ]
    return " ".join(str(part) for part in parts if part) or None


def _merge_places(
    existing: list[RecommendedPlace], incoming: list[RecommendedPlace]
) -> list[RecommendedPlace]:
    merged = list(existing)
    for place in incoming:
        if not any(
            haversine_m(place.lat, place.lon, current.lat, current.lon) <= 50
            for current in merged
        ):
            merged.append(place)
    return merged


def _street_text(value: Any) -> str | None:
    """Street and number only, from the facility's own address (never the searched place)."""
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    parts = [
        value.get("street") or value.get("road"),
        value.get("house_number") or value.get("housenumber"),
    ]
    return " ".join(str(part) for part in parts if part) or None


_GENERIC_NAME = re.compile(
    r"(?:parkplatz|parkplätze|parkhaus|parkgarage|tiefgarage|garage|stellplatz|stellplätze|"
    r"parking|car park|p\s*[+&]\s*r|park\s*&\s*ride|bike parking|bicycle parking|"
    r"fahrradparkplatz|fahrradabstellanlage|ladestation|ladepunkt|ladesäule|"
    r"charging(?: station| point)?|charger|haltestelle|station|e-scooter|"
    r"shared (?:bicycle|vehicle)|mobility location)(?:\s+\d+[a-z]?)?",
    re.IGNORECASE,
)


def is_generic_name(name: str) -> bool:
    return _GENERIC_NAME.fullmatch(name.strip().strip(".,;:()")) is not None


def place_label(place: RecommendedPlace) -> str:
    """Facility name for buttons and pins; the street when the name is a generic word."""
    if is_generic_name(place.name) and place.street:
        return place.street
    return place.name


def _mention_position(text: str, place: RecommendedPlace) -> int | None:
    candidates = [place.street] if place.street else []
    if not is_generic_name(place.name):
        candidates.append(place.name)
    positions = [text.find(candidate.casefold()) for candidate in candidates]
    positions = [position for position in positions if position >= 0]
    return min(positions) if positions else None


def _places_for_answer(
    text: str, places: list[RecommendedPlace]
) -> list[RecommendedPlace]:
    """Places the answer mentions, in the order it mentions them; else the tool order."""
    normalized_text = text.casefold()
    mentioned = [
        (position, index, place)
        for index, place in enumerate(places)
        if (position := _mention_position(normalized_text, place)) is not None
    ]
    if mentioned:
        return [place for _position, _index, place in sorted(mentioned, key=lambda m: m[:2])][:3]
    return places[:3]


def _item_limit(tool_name: str) -> int:
    """Place tools feed navigation buttons, so the model sees three; catalogue lists show more."""
    return 3 if tool_name in _PLACE_TOOLS else 20


def _model_result_text(text: str, item_limit: int = 3, max_chars: int = 8000) -> str:
    """Keep the result count aligned with the items sent, dropping whole items to fit max_chars."""
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return text
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        return text
    total_count = value.get("count", len(value["items"]))
    items = value["items"][:item_limit]
    while True:
        value["items"] = items
        value["count"] = len(items)
        if total_count != len(items):
            value["total_count"] = total_count
            value["count_note"] = (
                "count is the number of supplied items; total_count is the full result count"
            )
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        if len(encoded) <= max_chars or len(items) <= 1:
            return encoded
        items = items[:-1]


def _default_place_name(kind: str) -> str:
    return {
        "bicycle": "Shared bicycle",
        "bike_parking": "Bicycle parking",
        "scooter": "E-scooter",
        "vehicle": "Shared vehicle",
        "station": "Station",
    }.get(kind, "Mobility location")


def _with_searched_place(
    text: str, place: tuple[str, str | None], question: str
) -> str:
    text = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("📍")
    ).strip()
    label, place_type = place
    is_german = _GERMAN_PATTERN.search(question) is not None
    if label == "shared Telegram location":
        label = "geteilter Telegram-Standort" if is_german else label
    detail = f"{label} ({place_type})" if place_type else label
    prefix = "📍 Gesucht um:" if is_german else "📍 Searched around:"
    return f"{prefix} {detail}\n{text}"