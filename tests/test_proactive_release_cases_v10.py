from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.proactive_dispatch_v10 import ProactiveProposalDispatcher
from app.proactive_intelligence_v10 import ConditionSpec, ProactiveConditionEngine
from app.proactive_lifecycle_v10 import ProactiveConditionLifecycle
from app.proactive_sources_v10 import ProactiveSourceRegistry, SourceContract
from plugins import proactive_intelligence_v10


@dataclass
class _Tool:
    risk: str
    gate: str | None = None


class _DB:
    def list_approvals(self, status="pending", limit=1000):
        return [{"id": "a1"}, {"id": "a2"}]

    def list_missions(self, limit=1000, status=None):
        return [
            {"id": "m1", "status": "running"},
            {"id": "m2", "status": "completed"},
        ]


class _Connectors:
    def list(self):
        return {"ok": True, "connectors": [{"id": "c1", "enabled": True}, {"id": "c2", "enabled": False}]}


class _Settings:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir


class _Registry:
    def __init__(self, tmp_path: Path):
        self.settings = _Settings(tmp_path)
        self.db = _DB()
        self.connectors = _Connectors()
        self.tools = {"notify": _Tool("external", "connectors"), "read_status": _Tool("read", None)}
        self.registered = {}
        self.execute_calls = []

    def register(self, name, description, parameters, function, gate=None, risk="read"):
        self.registered[name] = {"function": function, "risk": risk, "gate": gate}
        self.tools[name] = _Tool(risk, gate)

    def catalog(self):
        return [{"name": name, "description": "release", "risk": tool.risk, "gate": tool.gate} for name, tool in self.tools.items()]

    async def execute(self, name, arguments, permissions):
        self.execute_calls.append((name, arguments, permissions))
        return {"ok": False, "approval_required": True, "approval_id": "approval-release", "risk": "external"}


def test_release_trusted_source_integrity(tmp_path):
    now = 1000.0
    sources = ProactiveSourceRegistry(clock=lambda: now)
    sources.register_source(SourceContract("system.release", max_age_seconds=30), lambda: (5, now))
    evidence = sources.collect("system.release")

    assert evidence.trusted_for_dispatch is True
    assert evidence.source_digest
    assert evidence.expires_at == 1030.0
    evidence.require_fresh(now)


def test_release_lifecycle_persistence_and_recovery(tmp_path):
    clock = lambda: 1000.0
    sources = ProactiveSourceRegistry(clock=clock)
    sources.register_source(SourceContract("system.release", max_age_seconds=60), lambda: 3)
    engine = ProactiveConditionEngine(tmp_path / "engine.json", clock=clock)
    captured = []
    lifecycle = ProactiveConditionLifecycle(
        tmp_path / "lifecycle.json",
        engine=engine,
        sources=sources,
        tool_catalog=lambda: [{"name": "read_status", "risk": "read", "gate": None}],
        proposal_sink=lambda evaluation, evidence: captured.append(evaluation.proposal.proposal_id),
        clock=clock,
    )
    lifecycle.register(
        condition_id="release-lifecycle",
        source_id="system.release",
        operator="gte",
        threshold=2,
        action_tool="read_status",
        interval_seconds=30,
        cooldown_seconds=0,
        edge_triggered=False,
    )
    lifecycle.set_enabled("release-lifecycle", True)
    first = lifecycle.evaluate_due()
    assert len(first) == 1 and first[0].evaluated is True
    assert captured

    recovered = ProactiveConditionLifecycle(
        tmp_path / "lifecycle.json",
        engine=engine,
        sources=sources,
        tool_catalog=lambda: [{"name": "read_status", "risk": "read", "gate": None}],
        clock=clock,
    )
    assert recovered.get("release-lifecycle").enabled is True
    assert recovered.evaluate_due() == []


def test_release_duplicate_suppression(tmp_path):
    engine = ProactiveConditionEngine(tmp_path / "engine.json", clock=lambda: 1000.0)
    spec = ConditionSpec("edge", "gte", 1, "read_status", {}, cooldown_seconds=0, edge_triggered=True)
    catalog = [{"name": "read_status", "risk": "read", "gate": None}]

    first = engine.evaluate(spec, 1, tool_catalog=catalog)
    second = engine.evaluate(spec, 1, tool_catalog=catalog)

    assert first.proposed is True
    assert second.proposed is False
    assert second.suppressed_reason == "edge_already_active"


def test_release_approval_boundary_and_idempotency(tmp_path):
    registry = _Registry(tmp_path)
    proactive_intelligence_v10.register(registry)
    evaluate = registry.registered["evaluate_trusted_proactive_source"]["function"]
    result = evaluate(
        condition_id="approval-boundary",
        source_id="system.pending_approvals",
        operator="gte",
        threshold=2,
        action_tool="notify",
        action_args={"message": "review"},
        cooldown_seconds=0,
        edge_triggered=False,
    )
    proposal_id = result["proposal"]["proposal_id"]

    first = asyncio.run(registry.dispatch_cached_proactive_proposal_v10(proposal_id, {"allow_connectors": True}))
    replay = asyncio.run(registry.dispatch_cached_proactive_proposal_v10(proposal_id, {"allow_connectors": True}))

    assert first["receipt"]["status"] == "approval_pending"
    assert first["receipt"]["approval_id"] == "approval-release"
    assert replay["receipt"] == first["receipt"]
    assert len(registry.execute_calls) == 1


def test_release_mission_connector_source_integration(tmp_path):
    registry = _Registry(tmp_path)
    proactive_intelligence_v10.register(registry)

    mission_evidence = registry.proactive_sources_v10.collect("system.active_missions")
    connector_evidence = registry.proactive_sources_v10.collect("system.enabled_connectors")

    assert mission_evidence.value == 1
    assert connector_evidence.value == 1
    assert mission_evidence.trusted_for_dispatch is True
    assert connector_evidence.trusted_for_dispatch is True
    assert registry.execute_calls == []
