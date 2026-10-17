import pytest

from mobidata_bw_mcp.telegram_bot.mcp_bridge import server_url


def test_no_url_means_local_stdio(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    assert server_url() is None
    monkeypatch.setenv("MCP_SERVER_URL", "  ")
    assert server_url() is None


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8765/mcp", "http://localhost:8765/mcp", "https://example.test/mcp"],
)
def test_allowed_urls(monkeypatch, url):
    monkeypatch.setenv("MCP_SERVER_URL", url)
    assert server_url() == url


@pytest.mark.parametrize("url", ["http://example.test/mcp", "ftp://127.0.0.1/mcp", "example.test"])
def test_plain_http_off_loopback_is_refused(monkeypatch, url):
    monkeypatch.setenv("MCP_SERVER_URL", url)
    with pytest.raises(RuntimeError):
        server_url()
