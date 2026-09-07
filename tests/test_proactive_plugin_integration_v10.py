from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from plugins import proactive_intelligence_v10


@dataclass
class FakeTool:
    risk: str
    gate: str | None = None


class FakeDB:
    def list_approvals(self, status="pending", limit=1000):
        assert status == "pending"
        return [{"id": "a1"}, {"id": "a2"}]


class FakeSettings:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir


class FakeRegistry:
    def __init__(self, tmp_path):
        self.settings = FakeSettings(tmp_path)
        self.db = FakeDB()
        self.tools = {"notify": FakeTool("external", "connectors")}
        self.registered = {}
        self.execute_calls = []

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {"function": function, "risk": risk, "gate": gate, "parameters": parameters}
        self.tools[name] = FakeTool(risk, gate)

    def catalog(self):
        return [{"name": name, "description": "test", "risk": tool.risk, "gate": tool.gate} for name, tool in self.tools.items()]

    async def execute(self, name, arguments, permissions):
        self.execute_calls.append((name, arguments, permissions))
        return {"ok": False, "approval_required": True, "approval_id": "approval-9", "risk": "external"}


def test_plugin_registers_host_owned_source_and_keeps_dispatch_internal(tmp_path):
    registry = FakeRegistry(tmp_path)
    proactive_intelligence_v10.register(registry)

    assert "evaluate_trusted_proactive_source" in registry.registered
    assert "dispatch_proactive_proposal" not in registry.registered
    status = registry.registered["proactive_v10_status"]["function"]()
    assert status["sources"] == [{"source_id": "system.pending_approvals", "max_age_seconds": 30, "trusted_for_dispatch": True}]
    assert callable(registry.dispatch_cached_proactive_proposal_v10)


@pytest.mark.asyncio
async def test_trusted_source_evaluation_caches_bound_proposal_and_dispatch_reenters_registry(tmp_path):
    registry = FakeRegistry(tmp_path)
    proactive_intelligence_v10.register(registry)
    evaluate = registry.registered["evaluate_trusted_proactive_source"]["function"]

    result = evaluate(
        condition_id="pending-approval-alert",
        source_id="system.pending_approvals",
        operator="gte",
        threshold=2,
        action_tool="notify",
        action_args={"message": "Pending approvals require review"},
        cooldown_seconds=0,
        edge_triggered=False,
    )

    assert result["matched"] is True
    assert result["proposed"] is True
    assert result["trusted_source"] is True
    proposal_id = result["proposal"]["proposal_id"]
    assert proposal_id in registry.proactive_proposals_v10

    dispatched = await registry.dispatch_cached_proactive_proposal_v10(
        proposal_id,
        {"allow_connectors": True, "approval_mode": "standard"},
    )
    replay = await registry.dispatch_cached_proactive_proposal_v10(
        proposal_id,
        {"allow_connectors": True, "approval_mode": "standard"},
    )

    assert dispatched["receipt"]["status"] == "approval_pending"
    assert dispatched["receipt"]["approval_id"] == "approval-9"
    assert replay["receipt"] == dispatched["receipt"]
    assert len(registry.execute_calls) == 1


def test_manual_evaluation_stays_untrusted(tmp_path):
    registry = FakeRegistry(tmp_path)
    proactive_intelligence_v10.register(registry)
    evaluate = registry.registered["evaluate_proactive_condition"]["function"]

    result = evaluate("manual", "eq", 1, 1, "notify", {"message": "x"}, 0, False)

    assert result["proposed"] is True
    assert result["trusted_source"] is False
    assert result["proposal"]["trusted_source"] is False
    assert result["proposal"]["source_id"] == "manual"
