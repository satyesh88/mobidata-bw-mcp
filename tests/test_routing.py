from types import SimpleNamespace

import pytest

from mobidata_bw_mcp.clients import routing


@pytest.mark.asyncio
async def test_driving_hgv_line_uses_configured_openrouteservice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(
            json=lambda: {
                "features": [
                    {
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[9.2, 49.1], [9.3, 49.2]],
                        }
                    }
                ]
            }
        )

    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "secret-key")
    monkeypatch.setattr(routing.http, "request", fake_request)

    line = await routing.driving_hgv_line(
        [{"lat": 49.1, "lon": 9.2}, {"lat": 49.2, "lon": 9.3}]
    )

    assert list(line.coords) == [(9.2, 49.1), (9.3, 49.2)]
    assert calls[0][0] == "POST"
    assert calls[0][2]["headers"] == {"Authorization": "secret-key"}
    assert calls[0][2]["json_body"]["coordinates"] == [[9.2, 49.1], [9.3, 49.2]]


@pytest.mark.asyncio
async def test_driving_hgv_line_skips_request_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)

    assert (
        await routing.driving_hgv_line(
            [{"lat": 49.1, "lon": 9.2}, {"lat": 49.2, "lon": 9.3}]
        )
        is None
    )