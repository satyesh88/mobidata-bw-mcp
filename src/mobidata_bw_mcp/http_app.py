"""Hosted HTTP mode: API-key auth, rate limits and metadata-only request logs around /mcp.

Stores no user data. The log line carries key id, JSON-RPC method, tool name, status and latency;
never request bodies, query strings or client addresses.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

ACCESS_LOG = logging.getLogger("mobidata.access")
LOG = logging.getLogger(__name__)

DEFAULT_KEYS_FILE = "/etc/mobidata-mcp/keys"
KEY_ID = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_./-]{1,64}$")
MAX_BODY_BYTES = 1_048_576

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def hash_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class KeyStore:
    """API keys as `key_id:sha256` lines from a file and/or the MOBIDATA_MCP_KEYS variable."""

    def __init__(
        self, path: str | Path | None = None, inline: str | None = None, reload_seconds: float = 5
    ) -> None:
        self.path = Path(path) if path else None
        self.reload_seconds = reload_seconds
        self._inline = self._parse(inline or "")
        self._file_keys: dict[str, str] = {}
        self._mtime: float | None = None
        self._checked = 0.0
        self._refresh(force=True)

    @staticmethod
    def _parse(text: str) -> dict[str, str]:
        keys: dict[str, str] = {}
        for raw in text.replace(",", "\n").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key_id, _, digest = line.partition(":")
            if KEY_ID.match(key_id) and SHA256_HEX.match(digest.lower()):
                keys[key_id] = digest.lower()
            else:
                LOG.warning("Ignoring a malformed key entry")
        return keys

    def _refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked < self.reload_seconds:
            return
        self._checked = now
        if not self.path:
            return
        try:
            mtime = self.path.stat().st_mtime
            if mtime != self._mtime:
                self._file_keys = self._parse(self.path.read_text(encoding="utf-8"))
                self._mtime = mtime
        except OSError:
            self._file_keys, self._mtime = {}, None

    def __len__(self) -> int:
        self._refresh()
        return len({**self._file_keys, **self._inline})

    def lookup(self, token: str) -> str | None:
        """Return the key id for a valid token. Compares every entry in constant time."""
        self._refresh()
        digest = hash_key(token)
        found = None
        for key_id, stored in {**self._file_keys, **self._inline}.items():
            if hmac.compare_digest(digest, stored):
                found = key_id
        return found


class SlidingWindow:
    """Allows at most `limit` hits per `window` seconds for each key."""

    def __init__(
        self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> int | None:
        """Record a request. Returns seconds to wait when the limit is exceeded, else None."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, int(self.window - (now - hits[0])) + 1)
        hits.append(now)
        return None


class _TooLarge(Exception):
    pass


def _describe(body: bytes) -> tuple[str | None, str | None]:
    """JSON-RPC method and tool names only; arguments are never read into the log."""
    try:
        data = json.loads(body)
    except ValueError:
        return None, None
    methods: list[str] = []
    tools: list[str] = []
    for item in (data if isinstance(data, list) else [data])[:20]:
        if not isinstance(item, dict):
            continue
        method = item.get("method")
        if isinstance(method, str):
            methods.append(method if SAFE_NAME.match(method) else "?")
            params = item.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            if method == "tools/call" and isinstance(name, str):
                tools.append(name if SAFE_NAME.match(name) else "?")
    return ",".join(methods) or None, ",".join(tools) or None


class McpGateway:
    """ASGI wrapper: /health is open; everything else needs a valid key and is rate limited."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        keys: KeyStore | None,
        per_key_limit: int = 60,
        global_limit: int = 600,
        warmup: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.app, self.keys, self.warmup = app, keys, warmup
        self.per_key = SlidingWindow(per_key_limit)
        self.overall = SlidingWindow(global_limit)
        self._tasks: set[asyncio.Task[Any]] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, self._on_lifespan(receive), send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    def _on_lifespan(self, receive: Receive) -> Receive:
        async def wrapped() -> dict[str, Any]:
            message = await receive()
            if message["type"] == "lifespan.startup" and self.warmup:
                task = asyncio.create_task(self._warm())
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            return message

        return wrapped

    async def _warm(self) -> None:
        try:
            await self.warmup()  # type: ignore[misc]
        except Exception as exc:
            LOG.warning("Warm-up failed: %s", type(exc).__name__)

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["path"] == "/health" and scope["method"] in {"GET", "HEAD"}:
            await _respond(send, 200, {"status": "ok"})
            return
        started = time.perf_counter()
        info: dict[str, Any] = {"key_id": "-", "rpc": None, "tool": None, "status": 500}

        async def tracked_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                info["status"] = message["status"]
            await send(message)

        try:
            await self._guarded(scope, receive, tracked_send, info)
        finally:
            ACCESS_LOG.info(
                json.dumps(
                    {
                        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                        "key_id": info["key_id"],
                        "http": scope["method"],
                        "rpc": info["rpc"],
                        "tool": info["tool"],
                        "status": info["status"],
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                )
            )

    async def _guarded(
        self, scope: Scope, receive: Receive, send: Send, info: dict[str, Any]
    ) -> None:
        if (wait := self.overall.hit("*")) is not None:
            await _respond(send, 429, {"error": "rate_limited"}, {"retry-after": str(wait)})
            return
        if self.keys is not None:
            token = _bearer(scope)
            key_id = self.keys.lookup(token) if token else None
            if key_id is None:
                await _respond(
                    send,
                    401,
                    {"error": "invalid_or_missing_api_key"},
                    {"www-authenticate": 'Bearer realm="mobidata-bw-mcp"'},
                )
                return
            info["key_id"] = key_id
            if (wait := self.per_key.hit(key_id)) is not None:
                await _respond(send, 429, {"error": "rate_limited"}, {"retry-after": str(wait)})
                return
        if scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        try:
            body = await _read_body(receive)
        except _TooLarge:
            await _respond(send, 413, {"error": "request_too_large"})
            return
        info["rpc"], info["tool"] = _describe(body)
        await self.app(scope, _replay(body, receive), send)


def _bearer(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            if scheme.lower() == "bearer" and 0 < len(token.strip()) <= 200:
                return token.strip()
    return None


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return b""
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise _TooLarge
        chunks.append(chunk)
        if not message.get("more_body"):
            return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replay() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


async def _respond(
    send: Send, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> None:
    body = json.dumps(payload).encode("utf-8")
    all_headers = {"content-type": "application/json", "content-length": str(len(body))}
    all_headers.update(headers or {})
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(k.encode(), v.encode()) for k, v in all_headers.items()],
        }
    )
    await send({"type": "http.response.body", "body": body})


def transport_security_from_env() -> TransportSecuritySettings:
    """Host names the proxy may send, from MOBIDATA_MCP_ALLOWED_HOSTS (comma separated)."""
    raw = os.getenv("MOBIDATA_MCP_ALLOWED_HOSTS", "")
    configured = [host.strip() for host in raw.split(",") if host.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*configured, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[],
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # Library INFO logs include full URLs with user locations, so keep them off.
    for name in ("httpx", "httpcore", "mcp", "uvicorn", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    ACCESS_LOG.handlers = [handler]
    ACCESS_LOG.setLevel(logging.INFO)
    ACCESS_LOG.propagate = False


def serve(host: str, port: int, insecure_no_auth: bool = False) -> None:
    import uvicorn

    from .server import create_server
    from .tools import signs

    keys: KeyStore | None = None
    if not insecure_no_auth:
        keys = KeyStore(
            os.getenv("MOBIDATA_MCP_KEYS_FILE", DEFAULT_KEYS_FILE),
            os.getenv("MOBIDATA_MCP_KEYS"),
        )
        if len(keys) == 0:
            raise SystemExit(
                "No API keys configured. Create one with deploy/new-api-key.py, or pass "
                "--insecure-no-auth for local testing only."
            )
    server = create_server(
        host=host,
        port=port,
        stateless_http=True,
        transport_security=transport_security_from_env(),
        log_level="WARNING",
    )
    configure_logging()
    app = McpGateway(
        server.streamable_http_app(),
        keys,
        per_key_limit=int(os.getenv("MOBIDATA_MCP_RATE_PER_KEY", "60")),
        global_limit=int(os.getenv("MOBIDATA_MCP_RATE_GLOBAL", "600")),
        warmup=signs.sign_index,
    )
    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)
