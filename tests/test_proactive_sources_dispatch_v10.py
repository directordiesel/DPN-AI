from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.proactive_dispatch_v10 import ProactiveProposalDispatcher
from app.proactive_intelligence_v10 import ConditionSpec, ProactiveConditionEngine
from app.proactive_sources_v10 import ProactiveSourceError, ProactiveSourceRegistry, SourceContract


@dataclass
class FakeTool:
    risk: str
    gate: str | None = None


class FakeRegistry:
    def __init__(self, *, result=None):
        self.tools = {"notify": FakeTool("external", "connectors"), "record": FakeTool("write", None)}
        self.calls = []
        self.result = result or {"ok": True}

    def catalog(self):
        return [{"name": name, "risk": tool.risk, "gate": tool.gate, "description": "test"} for name, tool in self.tools.items()]

    async def execute(self, name, arguments, permissions):
        self.calls.append((name, arguments, permissions))
        return dict(self.result)


def _spec(tool="record"):
    return ConditionSpec(
        condition_id="inventory-low",
        operator="lt",
        threshold=5,
        action_tool=tool,
        action_args={"sku": "A-1"},
        cooldown_seconds=0,
        edge_triggered=False,
    )


def test_host_owned_source_collection_binds_provenance_and_freshness():
    sources = ProactiveSourceRegistry(clock=lambda: 100.0)
    sources.register_source(SourceContract("inventory.level", max_age_seconds=30), lambda: (3, 95.0))

    evidence = sources.collect("inventory.level")

    assert evidence.source_id == "inventory.level"
    assert evidence.value == 3
    assert evidence.observed_at == 95.0
    assert evidence.expires_at == 125.0
    assert evidence.trusted_for_dispatch is True
    assert len(evidence.source_digest) == 64
    assert sources.catalog()[0]["source_id"] == "inventory.level"


def test_stale_host_source_fails_closed_during_collection():
    sources = ProactiveSourceRegistry(clock=lambda: 100.0)
    sources.register_source(SourceContract("inventory.level", max_age_seconds=10), lambda: (3, 80.0))

    with pytest.raises(ProactiveSourceError, match="stale"):
        sources.collect("inventory.level")


@pytest.mark.asyncio
async def test_trusted_evidence_proposal_dispatches_once_and_replay_returns_receipt(tmp_path):
    registry = FakeRegistry(result={"ok": True, "stored": True})
    sources = ProactiveSourceRegistry(clock=lambda: 100.0)
    sources.register_source(SourceContract("inventory.level", max_age_seconds=30), lambda: (3, 100.0))
    evidence = sources.collect("inventory.level")
    engine = ProactiveConditionEngine(tmp_path / "conditions.json", clock=lambda: 100.0)
    evaluation = engine.evaluate_evidence(_spec("record"), evidence, tool_catalog=registry.catalog())
    proposal = evaluation.proposal
    assert proposal is not None
    assert proposal.trusted_source is True
    assert proposal.source_digest == evidence.source_digest
    assert proposal.execution_authorized is False

    dispatcher = ProactiveProposalDispatcher(registry, tmp_path / "receipts.json", clock=lambda: 105.0)
    first = await dispatcher.dispatch(proposal, evidence, permissions={"approval_mode": "standard"})
    second = await dispatcher.dispatch(proposal, evidence, permissions={"approval_mode": "standard"})

    assert first.status == "executed"
    assert second == first
    assert len(registry.calls) == 1


@pytest.mark.asyncio
async def test_external_dispatch_preserves_approval_pending_and_does_not_reissue(tmp_path):
    registry = FakeRegistry(result={"ok": False, "approval_required": True, "approval_id": "approval-1", "risk": "external"})
    sources = ProactiveSourceRegistry(clock=lambda: 200.0)
    sources.register_source(SourceContract("alert.source", max_age_seconds=60), lambda: (1, 200.0))
    evidence = sources.collect("alert.source")
    engine = ProactiveConditionEngine(tmp_path / "conditions.json", clock=lambda: 200.0)
    spec = ConditionSpec("alert", "eq", 1, "notify", {"message": "alert"}, 0, False)
    proposal = engine.evaluate_evidence(spec, evidence, tool_catalog=registry.catalog()).proposal
    assert proposal is not None and proposal.approval_required is True

    dispatcher = ProactiveProposalDispatcher(registry, tmp_path / "receipts.json", clock=lambda: 201.0)
    first = await dispatcher.dispatch(proposal, evidence, permissions={"allow_connectors": True, "approval_mode": "standard"})
    second = await dispatcher.dispatch(proposal, evidence, permissions={"allow_connectors": True, "approval_mode": "standard"})

    assert first.status == "approval_pending"
    assert first.approval_id == "approval-1"
    assert second == first
    assert len(registry.calls) == 1


@pytest.mark.asyncio
async def test_manual_untrusted_observation_cannot_enter_dispatch(tmp_path):
    registry = FakeRegistry()
    engine = ProactiveConditionEngine(tmp_path / "conditions.json", clock=lambda: 100.0)
    proposal = engine.evaluate(_spec("record"), 3, tool_catalog=registry.catalog()).proposal
    assert proposal is not None and proposal.trusted_source is False

    sources = ProactiveSourceRegistry(clock=lambda: 100.0)
    sources.register_source(SourceContract("manual", max_age_seconds=30, trusted_for_dispatch=False), lambda: 3)
    evidence = sources.collect("manual")
    dispatcher = ProactiveProposalDispatcher(registry, tmp_path / "receipts.json", clock=lambda: 100.0)

    with pytest.raises(ProactiveSourceError, match="untrusted"):
        await dispatcher.dispatch(proposal, evidence, permissions={})
    assert registry.calls == []


@pytest.mark.asyncio
async def test_dispatch_blocks_stale_evidence_and_tool_metadata_drift(tmp_path):
    registry = FakeRegistry()
    sources = ProactiveSourceRegistry(clock=lambda: 100.0)
    sources.register_source(SourceContract("inventory.level", max_age_seconds=10), lambda: (3, 100.0))
    evidence = sources.collect("inventory.level")
    engine = ProactiveConditionEngine(tmp_path / "conditions.json", clock=lambda: 100.0)
    proposal = engine.evaluate_evidence(_spec("record"), evidence, tool_catalog=registry.catalog()).proposal
    assert proposal is not None

    stale_dispatcher = ProactiveProposalDispatcher(registry, tmp_path / "stale.json", clock=lambda: 111.0)
    with pytest.raises(ProactiveSourceError, match="stale"):
        await stale_dispatcher.dispatch(proposal, evidence, permissions={})

    registry.tools["record"].risk = "destructive"
    drift_dispatcher = ProactiveProposalDispatcher(registry, tmp_path / "drift.json", clock=lambda: 105.0)
    with pytest.raises(ValueError, match="risk/gate metadata changed"):
        await drift_dispatcher.dispatch(proposal, evidence, permissions={})
    assert registry.calls == []
