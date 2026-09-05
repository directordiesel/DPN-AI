import asyncio

from app.research_intelligence import ResearchIntelligence
from app.web_research_runtime import WebResearchRuntime


async def _search(query: str, limit: int):
    return {
        "ok": True,
        "query": query,
        "results": [
            {"title": "A", "url": "https://example.com/a?utm_source=x", "snippet": "alpha beta"},
            {"title": "B", "url": "https://www.noaa.gov/b", "snippet": "alpha beta"},
            {"title": "C", "url": "https://example.org/c", "snippet": "alpha beta"},
        ][:limit],
    }


async def _fetch(url: str, max_chars: int):
    if "example.org" in url:
        return {"ok": False, "error": "network error"}
    return {"ok": True, "url": url, "title": "Fetched", "content": ("alpha beta " * 100)[:max_chars]}


def test_runtime_fetches_bounded_sources_and_returns_citations():
    runtime = WebResearchRuntime(
        _search,
        _fetch,
        intelligence=ResearchIntelligence(max_sources=5, max_content_chars=5000),
        max_search_results=3,
        max_fetches=2,
    )
    result = asyncio.run(runtime.research("alpha beta"))
    assert result["ok"] is True
    assert result["searched"] == 3
    assert result["fetched"] == 2
    assert result["citations"]
    assert result["context"]


def test_runtime_preserves_partial_results_when_fetch_fails():
    async def search(query: str, limit: int):
        return {"ok": True, "results": [{"title": "C", "url": "https://example.org/c", "snippet": query}]}

    runtime = WebResearchRuntime(search, _fetch, max_search_results=1, max_fetches=1)
    result = asyncio.run(runtime.research("alpha beta"))
    assert result["ok"] is True
    assert result["partial"] is True
    assert result["fetched"] == 0
    assert result["fetch_failures"][0]["url"] == "https://example.org/c"


def test_runtime_fails_closed_when_search_fails():
    async def search(_query: str, _limit: int):
        return {"ok": False, "error": "search unavailable"}

    runtime = WebResearchRuntime(search, _fetch)
    result = asyncio.run(runtime.research("alpha"))
    assert result["ok"] is False
    assert result["error"] == "search unavailable"
    assert result["sources"] == []


def test_runtime_rejects_empty_query_without_network_calls():
    calls = {"search": 0}

    async def search(_query: str, _limit: int):
        calls["search"] += 1
        return {"ok": True, "results": []}

    runtime = WebResearchRuntime(search, _fetch)
    result = asyncio.run(runtime.research("   "))
    assert result["ok"] is False
    assert calls["search"] == 0
