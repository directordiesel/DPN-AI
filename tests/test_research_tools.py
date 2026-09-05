from app.tools.research import ResearchTools, install_research_tools
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


class FakeRegistry:
    def __init__(self):
        self.registered = {}

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {
            "description": description,
            "parameters": parameters,
            "function": function,
            "gate": gate,
            "risk": risk,
        }


def test_install_research_tools_registers_core_capabilities():
    registry = FakeRegistry()
    tools = install_research_tools(registry)

    assert registry.research is tools
    assert set(registry.registered) == {"research_web", "detect_claim_conflicts"}
    assert registry.registered["research_web"]["gate"] == "web"
    assert registry.registered["research_web"]["risk"] == "external"
    assert registry.registered["detect_claim_conflicts"]["risk"] == "read"
    assert registry.registered["research_web"]["parameters"]["additionalProperties"] is False
