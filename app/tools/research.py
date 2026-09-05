from __future__ import annotations

from typing import Any

from app.research_intelligence import ResearchIntelligence
from app.tools.web_tools import fetch_web_page, search_web
from app.web_research_runtime import WebResearchRuntime


class ResearchTools:
    """First-class adapter from the existing web boundary to v9 research intelligence."""

    def __init__(self) -> None:
        self.intelligence = ResearchIntelligence(max_sources=12, max_content_chars=60_000)
        self.runtime = WebResearchRuntime(
            search_web,
            fetch_web_page,
            intelligence=self.intelligence,
            max_search_results=10,
            max_fetches=6,
            fetch_chars=20_000,
            max_parallel_fetches=3,
        )

    async def research_web(self, query: str) -> dict[str, Any]:
        return await self.runtime.research(query)

    def detect_claim_conflicts(self, claims: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "ok": True,
            "conflicts": self.intelligence.detect_conflicts(claims),
            "claim_count": len(claims),
        }
