from app.tools.research import ResearchTools
from app.web_research_runtime import WebResearchRuntime


def test_research_tools_exposes_bounded_runtime():
    tools = ResearchTools()
    assert isinstance(tools.runtime, WebResearchRuntime)
    assert tools.runtime.max_search_results == 10
    assert tools.runtime.max_fetches == 6
    assert tools.runtime.max_parallel_fetches == 3


def test_research_tools_detects_claim_conflicts():
    tools = ResearchTools()
    result = tools.detect_claim_conflicts([
        {"claim": "Service is available", "stance": "supports", "source_ids": ["a"], "confidence": 0.9},
        {"claim": "Service is available", "stance": "refutes", "source_ids": ["b"], "confidence": 0.8},
    ])
    assert result["ok"] is True
    assert result["claim_count"] == 2
    assert result["conflicts"][0]["status"] == "conflict"
