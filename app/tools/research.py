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


def install_research_tools(registry: Any) -> ResearchTools:
    """Install v9 research intelligence as core ToolRegistry capabilities.

    This hook is called from the core plugin initialization path, before optional
    user plugins are loaded, so the research tools are available in the unified
    registry without relying on a configurable plugin file.
    """
    tools = ResearchTools()
    registry.research = tools

    registry.register(
        "research_web",
        "Run bounded multi-source web research with source authority, freshness, relevance scoring, deduplication, and citation-ready evidence.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        tools.research_web,
        gate="web",
        risk="external",
    )
    registry.register(
        "detect_claim_conflicts",
        "Detect conflicting stances for the same research claim using explicit source evidence references.",
        {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string"},
                            "stance": {"type": "string"},
                            "source_ids": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                        },
                        "required": ["claim", "stance"],
                    },
                }
            },
            "required": ["claims"],
            "additionalProperties": False,
        },
        tools.detect_claim_conflicts,
        risk="read",
    )
    return tools
