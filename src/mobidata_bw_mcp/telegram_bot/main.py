import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import InvalidToken
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..transit_format import render_departures
from ..version import log_startup
from .agent import (
    MobilityAgent,
    RecommendedPlace,
    recommended_place,
    short_place_label,
)
from .formatting import answer_html
from .limits import DailyBudget, HourlyRateLimiter
from .mcp_bridge import MCPBridge, result_text
from .texts import (
    ABOUT_TEXT,
    BUDGET_TEXT,
    ERROR_TEXT,
    EXAMPLES,
    HELP_TEXT,
    LOCATION_TEXT,
    NOT_ALLOWED_TEXT,
    RATE_LIMIT_TEXT,
    RESET_TEXT,
    START_TEXT,
    TIMEOUT_TEXT,
)
from .tool_logging import logged_arguments

LOGGER = logging.getLogger("mobidata.telegram")
STATE_TTL = timedelta(minutes=30)
TELEGRAM_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
NEAR_ME_PATTERN = re.compile(
    r"\b(?:near me|my place|here|hier|bei mir|mein(?:em)? (?:ort|standort)|"
    r"in der nähe(?!\s+von\b))\b",
    re.IGNORECASE,
)


def uses_saved_location(question: str) -> bool:
    return NEAR_ME_PATTERN.search(question) is not None


def travel_mode(place: RecommendedPlace) -> str:
    if place.kind == "bike_parking":
        return "bicycling"
    return "driving" if place.kind in {"parking", "accessible_parking", "charger"} else "walking"


def navigation_url(place: RecommendedPlace) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&destination={place.lat},{place.lon}&travelmode={travel_mode(place)}"
    )


def navigation_keyboard(
    places: list[RecommendedPlace],
) -> InlineKeyboardMarkup | None:
    if not places:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🧭 {short_place_label(place)}", url=navigation_url(place))]
            for place in places[:3]
        ]
    )


def example_keyboard(count: int = 3) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(example, callback_data=f"example:{index}")]
            for index, example in enumerate(EXAMPLES[:count])
        ]
    )


@dataclass
class PendingQuestion:
    question: str
    query: str = ""
    suggestions: list[dict[str, str]] = field(default_factory=list)
    token: str = field(default_factory=lambda: secrets.token_hex(4))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + STATE_TTL)


@dataclass
class DepartureContinuation:
    data: dict
    request: dict
    offset: int = 8
    german: bool = False
    accessibility: bool = False
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + STATE_TTL)


@dataclass
class Conversation:
    messages: deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=6))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + STATE_TTL)


class EphemeralState:
    def __init__(self) -> None:
        self._pending: dict[int, PendingQuestion] = {}
        self.departure_pages: dict[int, DepartureContinuation] = {}
        self._conversations: dict[int, Conversation] = {}
        self._locations: dict[int, tuple[float, float, datetime]] = {}

    def history(self, chat_id: int, now: datetime | None = None) -> list[dict[str, str]]:
        current = now or datetime.now(UTC)
        conversation = self._conversations.get(chat_id)
        if conversation is None or conversation.expires_at <= current:
            self._conversations.pop(chat_id, None)
            return []
        return list(conversation.messages)

    def remember(self, chat_id: int, role: str, content: str) -> None:
        conversation = self._conversations.setdefault(chat_id, Conversation())
        conversation.expires_at = datetime.now(UTC) + STATE_TTL
        conversation.messages.append({"role": role, "content": content})

    def set_location(self, chat_id: int, latitude: float, longitude: float) -> None:
        self._locations[chat_id] = (
            latitude,
            longitude,
            datetime.now(UTC) + STATE_TTL,
        )

    def location(self, chat_id: int, now: datetime | None = None) -> tuple[float, float] | None:
        current = now or datetime.now(UTC)
        location = self._locations.get(chat_id)
        if location is None:
            return None
        latitude, longitude, expires_at = location
        if expires_at <= current:
            self._locations.pop(chat_id, None)
            return None
        return latitude, longitude

    def pending(self, chat_id: int) -> PendingQuestion | None:
        value = self._pending.get(chat_id)
        if value and value.expires_at <= datetime.now(UTC):
            self._pending.pop(chat_id, None)
            return None
        return value

    def clear(self, chat_id: int) -> None:
        self.departure_pages.pop(chat_id, None)
        self._pending.pop(chat_id, None)
        self._conversations.pop(chat_id, None)
        self._locations.pop(chat_id, None)


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    anthropic_model: str
    daily_budget_usd: float
    user_limit_per_hour: int
    allowed_user_ids: frozenset[int]
    max_tool_rounds: int
    anthropic_workspace_id: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not telegram_token or not anthropic_key:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY must be set")
        if TELEGRAM_TOKEN_PATTERN.fullmatch(telegram_token) is None:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN has an invalid format; check the .env assignment"
            )
        allowed = frozenset(
            int(value.strip())
            for value in os.getenv("ALLOWED_USER_IDS", "").split(",")
            if value.strip()
        )
        return cls(
            telegram_token=telegram_token,
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"),
            daily_budget_usd=float(os.getenv("DAILY_BUDGET_USD", "10")),
            user_limit_per_hour=int(os.getenv("USER_MSG_LIMIT_PER_HOUR", "10")),
            allowed_user_ids=allowed,
            max_tool_rounds=int(os.getenv("MAX_TOOL_ROUNDS", "10")),
            anthropic_workspace_id=os.getenv("ANTHROPIC_WORKSPACE_ID") or None,
        )


class BotHandlers:
    def __init__(self, settings: Settings, bridge: MCPBridge) -> None:
        self.settings = settings
        self.bridge = bridge
        self.agent: MobilityAgent | None = None
        self.state = EphemeralState()
        self.rate_limiter = HourlyRateLimiter(settings.user_limit_per_hour)
        self.budget = DailyBudget(settings.daily_budget_usd)
        self._log_salt = secrets.token_bytes(16)

    async def startup(self, _application: Application) -> None:
        log_startup("mobidata-bot")
        await self.bridge.start()
        self.agent = MobilityAgent(
            self.bridge,
            self.settings.anthropic_model,
            self.settings.max_tool_rounds,
            self.settings.anthropic_workspace_id,
        )
        LOGGER.info("ready tools=%d", len(self.bridge.tools))

    async def shutdown(self, _application: Application) -> None:
        await self.bridge.close()

    async def start(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        keyboard = [
            [InlineKeyboardButton(example, callback_data=f"example:{index}")]
            for index, example in enumerate(EXAMPLES)
        ]
        await update.effective_message.reply_text(
            START_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True,
        )

    async def help(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(HELP_TEXT)

    async def about(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            ABOUT_TEXT,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    async def reset(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        self.state.clear(update.effective_chat.id)
        await update.effective_message.reply_text(RESET_TEXT)

    async def save_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if (
            self.settings.allowed_user_ids
            and update.effective_user.id not in self.settings.allowed_user_ids
        ):
            return
        location = update.effective_message.location
        self.state.set_location(
            update.effective_chat.id,
            location.latitude,
            location.longitude,
        )
        pending = self.state.pending(update.effective_chat.id)
        await update.effective_message.reply_text(
            "📍 Location received." if pending else LOCATION_TEXT,
            reply_markup=ReplyKeyboardRemove(),
        )
        if pending:
            self.state._pending.pop(update.effective_chat.id, None)
            question = pending.question
            if not uses_saved_location(question):
                question = (
                    re.sub(re.escape(pending.query), "my place", question, flags=re.I)
                    if pending.query
                    else f"{question} near me"
                )
                if not uses_saved_location(question):
                    question += " near me"
            await self._answer(update, context, question)

    async def example(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        if query.data.startswith("place:"):
            pending = self.state.pending(update.effective_chat.id)
            _, token, index_text = query.data.split(":", 2)
            if pending is None or pending.token != token:
                await context.bot.send_message(
                    update.effective_chat.id,
                    "That choice expired; please send your question again.",
                )
                return
            try:
                selected = pending.suggestions[int(index_text)]
            except (IndexError, ValueError):
                return
            self.state._pending.pop(update.effective_chat.id, None)
            question = (
                re.sub(
                    re.escape(pending.query),
                    lambda _: selected["location"],
                    pending.question,
                    flags=re.I,
                )
                if pending.query
                else pending.question
            )
            if question == pending.question:
                question += f"\nConfirmed search location: {selected['location']}"
            await self._answer(update, context, question)
            return
        try:
            index = int(query.data.partition(":")[2])
            question = EXAMPLES[index]
        except (IndexError, ValueError):
            return
        await self._answer(update, context, question)

    async def question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        question = update.effective_message.text
        if question.strip().casefold().rstrip("?!. ") in {"more", "mehr"}:
            continuation = self.state.departure_pages.get(update.effective_chat.id)
            if continuation:
                await self._more_departures(update, context, continuation)
                return
        pending = self.state.pending(update.effective_chat.id)
        if pending:
            entered_location = question
            if pending.query and pending.query.casefold() in pending.question.casefold():
                question = re.sub(
                    re.escape(pending.query),
                    lambda _: entered_location,
                    pending.question,
                    flags=re.I,
                )
            elif uses_saved_location(pending.question):
                question = NEAR_ME_PATTERN.sub(
                    lambda _: f"near {entered_location}",
                    pending.question,
                )
            else:
                question = f"{pending.question}\nConfirmed search location: {question}"
            self.state._pending.pop(update.effective_chat.id, None)
            await update.effective_message.reply_text(
                "I’ll use that location.",
                reply_markup=ReplyKeyboardRemove(),
            )
        await self._answer(update, context, question)

    async def _more_departures(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: DepartureContinuation
    ) -> None:
        chat_id, user_id = update.effective_chat.id, update.effective_user.id
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            return
        if not self.rate_limiter.allow(user_id):
            await context.bot.send_message(chat_id, RATE_LIMIT_TEXT)
            return
        if page.expires_at <= datetime.now(UTC):
            self.state.departure_pages.pop(chat_id, None)
            await context.bot.send_message(
                chat_id, "Please repeat your departure question for fresh data."
            )
            return
        if page.offset >= len(page.data.get("items", [])):
            cursor = page.data.get("next_cursor")
            if cursor is None or page.request["tool"] != "get_live_departures":
                self.state.departure_pages.pop(chat_id, None)
                await context.bot.send_message(
                    chat_id, "No further departures were found in this window."
                )
                return
            arguments = dict(page.request["arguments"])
            arguments["cursor"] = cursor
            for key in ("time_from", "time_to"):
                if page.data.get("query", {}).get(key):
                    arguments[key] = page.data["query"][key]
            started = time.monotonic()
            LOGGER.info(
                "tool_call name=get_live_departures arguments=%s",
                json.dumps(logged_arguments(arguments)),
            )
            try:
                async with asyncio.timeout(15):
                    result = await self.bridge.call_tool("get_live_departures", arguments)
                data = json.loads(result_text(result))
                if result.isError or data.get("error"):
                    raise ValueError("source lookup failed")
            except Exception:
                await context.bot.send_message(
                    chat_id, "I couldn’t retrieve further departures; please try again shortly."
                )
                return
            finally:
                LOGGER.info(
                    "tool name=get_live_departures duration_ms=%.0f",
                    (time.monotonic() - started) * 1000,
                )
            page.data = data
            page.offset = 0
        text, page.offset = render_departures(
            page.data, page.offset, page.german, page.accessibility
        )
        await context.bot.send_message(
            chat_id,
            answer_html(text, limit=4000),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        self.state.remember(chat_id, "assistant", text)
        if page.offset >= len(page.data.get("items", [])) and page.data.get("next_cursor") is None:
            self.state.departure_pages.pop(chat_id, None)

    async def _answer(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        question: str,
    ) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            await context.bot.send_message(chat_id, NOT_ALLOWED_TEXT)
            return
        if not self.rate_limiter.allow(user_id):
            await context.bot.send_message(chat_id, RATE_LIMIT_TEXT)
            return
        if not self.budget.available():
            await context.bot.send_message(chat_id, BUDGET_TEXT)
            return
        if self.agent is None:
            await context.bot.send_message(chat_id, ERROR_TEXT)
            return

        if uses_saved_location(question) and self.state.location(chat_id) is None:
            self.state._pending[chat_id] = PendingQuestion(question)
            await context.bot.send_message(
                chat_id,
                "Please share your location or send a street and city so I can search nearby.",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("📍 Share my location", request_location=True)]],
                    resize_keyboard=True,
                    one_time_keyboard=True,
                ),
            )
            return
        self.state._pending.pop(chat_id, None)
        self.state.departure_pages.pop(chat_id, None)

        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        started = time.monotonic()
        progress = None

        async def show_progress() -> None:
            nonlocal progress
            await asyncio.sleep(8)
            progress = await context.bot.send_message(
                chat_id, "⏳ Checking parking, station access and connections…"
            )

        async def delete_progress() -> None:
            if progress is not None:
                try:
                    await progress.delete()
                except Exception:
                    LOGGER.warning("progress_delete_failed")

        progress_task = asyncio.create_task(show_progress())
        try:
            async with asyncio.timeout(75):
                answer = await self.agent.answer(
                    question,
                    self.state.history(chat_id),
                    self.state.location(chat_id) if uses_saved_location(question) else None,
                )
        except TimeoutError:
            await context.bot.send_message(chat_id, TIMEOUT_TEXT)
            await delete_progress()
            return
        except Exception as error:
            LOGGER.error(
                "question_failed user=%s error=%s", self._user_hash(user_id), type(error).__name__
            )
            await context.bot.send_message(chat_id, ERROR_TEXT)
            await delete_progress()
            return

        finally:
            progress_task.cancel()
            await asyncio.gather(progress_task, return_exceptions=True)

        self.budget.add_usage(
            self.settings.anthropic_model,
            answer.input_tokens,
            answer.output_tokens,
        )
        if answer.clarification:
            pending = PendingQuestion(question, answer.location_query, answer.suggestions)
            self.state._pending[chat_id] = pending
            keyboard = (
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                option["label"][:100],
                                callback_data=f"place:{pending.token}:{index}",
                            )
                        ]
                        for index, option in enumerate(pending.suggestions[:3])
                    ]
                )
                if pending.suggestions
                else None
            )
            await context.bot.send_message(chat_id, answer.text, reply_markup=keyboard)
            await delete_progress()
            return
        if (
            answer.departure_data
            and answer.departure_request
            and set(answer.tools_used)
            <= {"get_departures", "get_live_departures", "find_transit", "plan_transit_journey"}
        ):
            self.state.departure_pages[chat_id] = DepartureContinuation(
                answer.departure_data,
                answer.departure_request,
                german=bool(re.search(r"Abfahrt|morgen früh|Züge|Bahnen", question, re.I)),
                accessibility=bool(
                    re.search(r"wheelchair|accessible|barriere|rollstuhl", question, re.I)
                ),
            )
        self.state.remember(chat_id, "user", question)
        self.state.remember(chat_id, "assistant", answer.text)
        await context.bot.send_message(
            chat_id,
            answer_html(
                answer.text,
                limit=4000
                if any(
                    tool in answer.tools_used
                    for tool in {"get_departures", "get_live_departures", "plan_transit_journey"}
                )
                else 1200,
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=(
                example_keyboard() if answer.off_topic else navigation_keyboard(answer.places)
            ),
        )
        await delete_progress()
        if answer.places and not answer.off_topic:
            best_place = recommended_place(answer.text, answer.places)
            await context.bot.send_venue(
                chat_id,
                latitude=best_place.lat,
                longitude=best_place.lon,
                title=short_place_label(best_place),
                address=best_place.address[:256],
            )
        LOGGER.info(
            "question user=%s tools=%s stop_reason=%s tool_rounds=%d "
            "input_tokens=%d output_tokens=%d latency_s=%.1f",
            self._user_hash(user_id),
            ",".join(answer.tools_used) or "none",
            answer.stop_reason or "unknown",
            answer.tool_rounds,
            answer.input_tokens,
            answer.output_tokens,
            time.monotonic() - started,
        )

    def _user_hash(self, user_id: int) -> str:
        return hashlib.blake2b(str(user_id).encode(), key=self._log_salt, digest_size=8).hexdigest()


def build_application(settings: Settings) -> Application:
    bridge = MCPBridge()
    handlers = BotHandlers(settings, bridge)
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .post_init(handlers.startup)
        .post_shutdown(handlers.shutdown)
        .build()
    )
    private = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", handlers.start, filters=private))
    application.add_handler(CommandHandler("help", handlers.help, filters=private))
    application.add_handler(CommandHandler("reset", handlers.reset, filters=private))
    application.add_handler(CommandHandler("about", handlers.about, filters=private))
    application.add_handler(
        CallbackQueryHandler(
            handlers.example,
            pattern=r"^(?:example:\d+|place:[a-f0-9]{8}:\d+)$",
        )
    )
    application.add_handler(MessageHandler(private & filters.LOCATION, handlers.save_location))
    application.add_handler(
        MessageHandler(private & filters.TEXT & ~filters.COMMAND, handlers.question)
    )
    return application


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_environment()
    try:
        build_application(settings).run_polling(
            allowed_updates=Update.ALL_TYPES,
            bootstrap_retries=3,
        )
    except InvalidToken:
        raise SystemExit("Telegram rejected TELEGRAM_BOT_TOKEN; check .env and BotFather") from None


if __name__ == "__main__":
    main()
