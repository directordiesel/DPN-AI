from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from app.research_intelligence import ResearchIntelligence


SearchFn = Callable[[str, int], Awaitable[dict[str, Any]]]
FetchFn = Callable[[str, int], Awaitable[dict[str, Any]]]


class WebResearchRuntime:
    """Bounded search -> fetch -> rank research pipeline.

    Network safety remains the responsibility of the existing web tool layer.
    This runtime adds deterministic limits, graceful partial failure handling,
    evidence ranking, and citation-ready output for downstream agents.
    """

    def __init__(
        self,
        search_fn: SearchFn,
        fetch_fn: FetchFn,
        *,
        intelligence: ResearchIntelligence | None = None,
        max_search_results: int = 10,
        max_fetches: int = 6,
        fetch_chars: int = 20_000,
        max_parallel_fetches: int = 3,
    ) -> None:
        if not 1 <= max_search_results <= 20:
            raise ValueError("max_search_results must be between 1 and 20")
        if not 0 <= max_fetches <= max_search_results:
            raise ValueError("max_fetches must be between 0 and max_search_results")
        if not 1_000 <= fetch_chars <= 50_000:
            raise ValueError("fetch_chars must be between 1000 and 50000")
        if not 1 <= max_parallel_fetches <= 8:
            raise ValueError("max_parallel_fetches must be between 1 and 8")
        self.search_fn = search_fn
        self.fetch_fn = fetch_fn
        self.intelligence = intelligence or ResearchIntelligence(max_sources=max_search_results)
        self.max_search_results = max_search_results
        self.max_fetches = max_fetches
        self.fetch_chars = fetch_chars
        self.max_parallel_fetches = max_parallel_fetches

    async def research(self, query: str) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "query is required", "sources": [], "citations": [], "context": ""}

        search = await self.search_fn(query, self.max_search_results)
        if not isinstance(search, dict) or not search.get("ok"):
            return {
                "ok": False,
                "error": (search or {}).get("error", "web search failed") if isinstance(search, dict) else "web search failed",
                "query": query,
                "sources": [],
                "citations": [],
                "context": "",
            }

        raw_results = [dict(item) for item in search.get("results", []) if isinstance(item, dict)]
        prelim = self.intelligence.build_sources(query, raw_results)
        urls = [source.url for source in prelim[: self.max_fetches]]
        semaphore = asyncio.Semaphore(self.max_parallel_fetches)

        async def fetch_one(url: str) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                try:
                    result = await self.fetch_fn(url, self.fetch_chars)
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": f"fetch failed: {exc}"}
                return url, result if isinstance(result, dict) else {"ok": False, "error": "invalid fetch result"}

        fetched_pairs = await asyncio.gather(*(fetch_one(url) for url in urls)) if urls else []
        fetched_by_url = {url: result for url, result in fetched_pairs}

        enriched: list[dict[str, Any]] = []
        fetch_failures: list[dict[str, str]] = []
        for item in raw_results:
            normalized = self.intelligence.normalize_url(str(item.get("url") or ""))
            enriched_item = dict(item)
            fetch_result = fetched_by_url.get(normalized)
            if fetch_result:
                if fetch_result.get("ok"):
                    enriched_item["url"] = fetch_result.get("url") or normalized
                    enriched_item["title"] = fetch_result.get("title") or enriched_item.get("title")
                    enriched_item["content"] = fetch_result.get("content") or ""
                else:
                    fetch_failures.append({"url": normalized, "error": str(fetch_result.get("error") or "fetch failed")})
            enriched.append(enriched_item)

        bundle = self.intelligence.evidence_bundle(query, enriched)
        bundle.update({
            "searched": len(raw_results),
            "fetched": sum(1 for _url, result in fetched_pairs if result.get("ok")),
            "fetch_failures": fetch_failures,
            "partial": bool(fetch_failures),
        })
        return bundle
