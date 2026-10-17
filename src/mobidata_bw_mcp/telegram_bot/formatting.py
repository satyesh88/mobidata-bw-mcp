import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

from .texts import ATTRIBUTION

TRUNCATION_NOTICE = "… (reply 'more' for the rest)"
EMPTY_REPLY = "Sorry, I couldn’t produce an answer from the available data."
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


class TelegramHTMLSanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"b", "i"}:
            self.parts.append(f"<{tag}>")
            self.open_tags.append(tag)
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if urlparse(href).scheme in {"http", "https"}:
                self.parts.append(f'<a href="{escape(href, quote=True)}">')
                self.open_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.open_tags and self.open_tags[-1] == tag:
            self.parts.append(f"</{tag}>")
            self.open_tags.pop()

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))

    def result(self) -> str:
        return "".join(self.parts) + "".join(f"</{tag}>" for tag in reversed(self.open_tags))


def safe_html(text: str, limit: int = 1200) -> str:
    text = _MARKDOWN_BOLD.sub(r"<b>\1</b>", text)
    sanitizer = TelegramHTMLSanitizer()
    sanitizer.feed(text)
    sanitized = sanitizer.result().strip()
    if len(sanitized) <= limit:
        return sanitized
    plain = _plain_text(text).strip()
    available = max(0, limit - len(TRUNCATION_NOTICE) - 1)
    prefix = plain[:available]
    prefix = (
        prefix.rsplit("\n", 1)[0]
        if "\n" in prefix
        else prefix.rsplit(" ", 1)[0] or prefix
    )
    return f"{escape(prefix.rstrip())}\n{escape(TRUNCATION_NOTICE)}"


def is_search_header(line: str) -> bool:
    return re.match(
        r"^\s*(?:📍\s*)?(?:Searched around|Gesucht um)\s*:", line, re.IGNORECASE
    ) is not None


def answer_html(text: str, limit: int = 1200) -> str:
    # Keep the raw answer for pin selection; hide machine metadata only at rendering.
    lines = []
    seen_header = False
    for line in text.splitlines():
        if re.match(r"^\s*(?:Recommendation|Empfehlung):", line, re.IGNORECASE):
            continue
        if is_search_header(line):
            if seen_header:
                continue
            seen_header = True
        lines.append(line)
    text = "\n".join(lines)
    if text.strip() in {
        "The accessibility lookup failed",
        "The mobility lookup failed",
    }:
        return safe_html(text.strip(), limit)
    body = text.replace(ATTRIBUTION, "").strip() or EMPTY_REPLY
    suffix = f"\n{ATTRIBUTION}"
    return safe_html(body, limit - len(suffix)) + suffix


def _plain_text(text: str) -> str:
    parser = TelegramHTMLSanitizer()
    parser.feed(text)
    return "".join(part for part in parser.parts if not part.startswith("<"))