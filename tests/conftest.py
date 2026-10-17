import pytest

from mobidata_bw_mcp.clients import traffic_messages


@pytest.fixture(autouse=True)
def no_live_traffic_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty() -> tuple[None, list]:
        return None, []

    monkeypatch.setattr(traffic_messages, "messages", empty)
