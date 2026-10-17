import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mobidata_bw_mcp import server as server_module
from mobidata_bw_mcp.http_app import (
    KeyStore,
    McpGateway,
    SlidingWindow,
    _describe,
    hash_key,
)
from mobidata_bw_mcp.server import create_server

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "new-api-key.py"
TOKEN = "mdbw_test-token"


async def echo_app(scope, receive, send):
    if scope["type"] != "http":
        return
    message = await receive()
    body = message.get("body", b"")
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def make_client(per_key=60, global_limit=600, keys=True):
    store = KeyStore(inline=f"alice:{hash_key(TOKEN)}") if keys else None
    app = McpGateway(echo_app, store, per_key_limit=per_key, global_limit=global_limit)
    return TestClient(app)


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_health_needs_no_key():
    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_or_wrong_key_is_rejected():
    client = make_client()
    assert client.post("/mcp", content=b"{}").status_code == 401
    wrong = client.post("/mcp", content=b"{}", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"].startswith("Bearer")
    other_scheme = client.post("/mcp", content=b"{}", headers={"Authorization": f"Basic {TOKEN}"})
    assert other_scheme.status_code == 401


def test_valid_key_passes_body_through():
    response = make_client().post("/mcp", content=b'{"jsonrpc":"2.0"}', headers=AUTH)
    assert response.status_code == 200
    assert response.content == b'{"jsonrpc":"2.0"}'


def test_per_key_limit_returns_429_with_retry_after():
    client = make_client(per_key=3)
    codes = [client.post("/mcp", content=b"{}", headers=AUTH).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert int(client.post("/mcp", content=b"{}", headers=AUTH).headers["retry-after"]) >= 1


def test_global_limit_applies_even_to_unauthenticated_requests():
    client = make_client(global_limit=2)
    codes = [client.post("/mcp", content=b"{}").status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_oversized_body_is_rejected():
    response = make_client().post("/mcp", content=b"x" * 1_100_000, headers=AUTH)
    assert response.status_code == 413


def test_insecure_mode_skips_auth():
    assert make_client(keys=False).post("/mcp", content=b"{}").status_code == 200


def test_log_has_metadata_only(caplog):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "find_parking", "arguments": {"location": "Secret Street 12"}},
        }
    ).encode()
    access = logging.getLogger("mobidata.access")
    access.addHandler(caplog.handler)
    access.setLevel(logging.INFO)
    try:
        make_client().post("/mcp?lat=48.7&lon=9.1", content=body, headers=AUTH)
    finally:
        access.removeHandler(caplog.handler)
    line = next(r.getMessage() for r in caplog.records if r.name == "mobidata.access")
    entry = json.loads(line)
    assert entry["key_id"] == "alice"
    assert entry["rpc"] == "tools/call"
    assert entry["tool"] == "find_parking"
    assert entry["status"] == 200
    assert "Secret" not in line and "48.7" not in line and TOKEN not in line


def test_describe_ignores_hostile_values():
    method, tool = _describe(
        json.dumps({"method": "tools/call", "params": {"name": "x\ny"}}).encode()
    )
    assert (method, tool) == ("tools/call", "?")
    assert _describe(b"not json") == (None, None)


def test_sliding_window_recovers():
    now = [0.0]
    window = SlidingWindow(2, window=60, clock=lambda: now[0])
    assert window.hit("k") is None
    assert window.hit("k") is None
    assert window.hit("k") is not None
    now[0] = 61
    assert window.hit("k") is None
    assert window.hit("other") is None


def test_key_store_reads_and_reloads_file(tmp_path):
    keys = tmp_path / "keys"
    keys.write_text(f"# comment\nbob:{hash_key('one')}\nbroken line\n")
    store = KeyStore(keys, reload_seconds=0)
    assert store.lookup("one") == "bob"
    assert store.lookup("two") is None
    with keys.open("a") as handle:
        handle.write(f"carol:{hash_key('two')}\n")
    store._mtime = None  # force reload without waiting for the file timestamp
    assert store.lookup("two") == "carol"


def test_missing_key_file_means_no_keys(tmp_path):
    assert len(KeyStore(tmp_path / "absent")) == 0


def test_key_script_creates_usable_private_key(tmp_path):
    keys = tmp_path / "sub" / "keys"
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "alice", "--file", str(keys)],
        capture_output=True,
        text=True,
        check=True,
    )
    token = run.stdout.strip()
    assert token.startswith("mdbw_")
    assert token not in keys.read_text()
    assert (keys.stat().st_mode & 0o777) == 0o600
    assert KeyStore(keys).lookup(token) == "alice"
    again = subprocess.run(
        [sys.executable, str(SCRIPT), "alice", "--file", str(keys)], capture_output=True, text=True
    )
    assert again.returncode == 1
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "bad name!", "--file", str(keys)],
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2


@pytest.fixture
def mcp_client(monkeypatch):
    from mcp.server.transport_security import TransportSecuritySettings

    async def no_warmup():
        return None

    monkeypatch.setattr(server_module.signs, "sign_index", no_warmup)
    server = create_server(
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=["testserver"]
        ),
        log_level="WARNING",
    )
    gateway = McpGateway(
        server.streamable_http_app(), KeyStore(inline=f"alice:{hash_key(TOKEN)}")
    )
    with TestClient(gateway) as client:
        yield client


MCP_HEADERS = {**AUTH, "Accept": "application/json, text/event-stream"}


def rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def test_mcp_endpoint_lists_tools_through_gateway(mcp_client):
    assert mcp_client.post("/mcp", json=rpc("tools/list")).status_code == 401
    init = mcp_client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json=rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        ),
    )
    assert init.status_code == 200
    listing = mcp_client.post("/mcp", headers=MCP_HEADERS, json=rpc("tools/list", id_=2))
    assert listing.status_code == 200
    assert "find_parking" in listing.text
    assert mcp_client.get("/health").json() == {"status": "ok"}
