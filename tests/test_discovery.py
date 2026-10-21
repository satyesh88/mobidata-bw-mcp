import pytest

from mobidata_bw_mcp.tools import discovery


@pytest.mark.asyncio
async def test_catalog_flags_missing_licence(monkeypatch) -> None:
    async def fake_search(query, limit, group=None):
        return {
            "count": 1,
            "results": [{"title": "Nextbike", "name": "nextbike", "resources": []}],
        }

    monkeypatch.setattr(discovery.ckan, "search", fake_search)

    result = await discovery.search_datasets("Fahrrad")

    assert result["items"][0]["licence_missing"] is True
    assert "Nextbike" in result["warnings"][0]



@pytest.mark.asyncio
async def test_search_filters_by_group_and_reports_total_matches(monkeypatch) -> None:
    seen = {}

    async def fake_search(query, limit, group=None):
        seen.update(query=query, limit=limit, group=group)
        return {
            "count": 15,
            "results": [
                {"title": "Parkdaten", "name": "p", "license_id": "dl", "resources": []}
            ],
        }

    monkeypatch.setattr(discovery.ckan, "search", fake_search)

    result = await discovery.search_datasets(group="parkraum", limit=1)

    assert seen == {"query": "", "limit": 1, "group": "parkraum"}
    assert result["query"]["total_matches"] == 15
    assert result["truncated"] is True
    assert any("1 of 15" in warning for warning in result["warnings"])



@pytest.mark.asyncio
async def test_empty_query_searches_everything(monkeypatch) -> None:
    seen = {}

    async def fake_action(name, params):
        seen.update(params)
        return {"count": 0, "results": []}

    monkeypatch.setattr(discovery.ckan, "_action", fake_action)

    await discovery.ckan.search("  ", 5, "parkraum")

    assert seen == {"q": "*:*", "rows": 5, "fq": "groups:parkraum"}

