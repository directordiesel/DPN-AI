from __future__ import annotations

import hashlib

import pytest

from app.full_system_integration_v10 import (
    FullSystemIntegrationGate,
    IntegrationError,
    IntegrationState,
    REQUIRED_V10_SUBSYSTEMS,
    SubsystemEvidence,
)


def _evidence(subsystem_id: str, *, state: IntegrationState = IntegrationState.READY, approval: bool = True) -> SubsystemEvidence:
    digest = hashlib.sha256(f"evidence:{subsystem_id}".encode("utf-8")).hexdigest()
    batch = min(REQUIRED_V10_SUBSYSTEMS.index(subsystem_id) + 1, 15)
    return SubsystemEvidence(
        subsystem_id=subsystem_id,
        batch=batch,
        state=state,
        release_gate=f"{subsystem_id}_release_gate",
        evidence_digest=digest,
        approval_boundary_preserved=approval,
    )


def test_full_system_gate_requires_every_v10_subsystem():
    gate = FullSystemIntegrationGate()
    evidence = [_evidence(item) for item in REQUIRED_V10_SUBSYSTEMS[:-1]]
    result = gate.evaluate(evidence)
    assert result.ready is False
    assert result.missing_subsystems == (REQUIRED_V10_SUBSYSTEMS[-1],)


def test_full_system_gate_passes_only_when_all_subsystems_are_ready():
    gate = FullSystemIntegrationGate()
    result = gate.evaluate(_evidence(item) for item in REQUIRED_V10_SUBSYSTEMS)
    assert result.ready is True
    assert result.blocked_subsystems == ()
    assert result.missing_subsystems == ()
    assert result.approval_boundary_failures == ()
    assert result.admitted_subsystems == tuple(sorted(REQUIRED_V10_SUBSYSTEMS))


def test_blocked_subsystem_prevents_integrated_readiness():
    gate = FullSystemIntegrationGate()
    evidence = [
        _evidence(item, state=IntegrationState.BLOCKED if item == "connector_protocol" else IntegrationState.READY)
        for item in REQUIRED_V10_SUBSYSTEMS
    ]
    result = gate.evaluate(evidence)
    assert result.ready is False
    assert result.blocked_subsystems == ("connector_protocol",)


def test_approval_boundary_regression_prevents_integrated_readiness():
    gate = FullSystemIntegrationGate()
    evidence = [
        _evidence(item, approval=item != "self_improvement")
        for item in REQUIRED_V10_SUBSYSTEMS
    ]
    result = gate.evaluate(evidence)
    assert result.ready is False
    assert result.approval_boundary_failures == ("self_improvement",)


def test_duplicate_or_unexpected_subsystems_fail_closed():
    gate = FullSystemIntegrationGate()
    item = _evidence("model_intelligence")
    with pytest.raises(IntegrationError, match="duplicate subsystem"):
        gate.evaluate([item, item])

    unexpected = SubsystemEvidence(
        subsystem_id="unknown_runtime",
        batch=15,
        state=IntegrationState.READY,
        release_gate="unknown",
        evidence_digest="a" * 64,
        approval_boundary_preserved=True,
    )
    with pytest.raises(IntegrationError, match="unexpected subsystem"):
        gate.evaluate([unexpected])


def test_integration_evidence_cannot_claim_side_effects():
    item = SubsystemEvidence(
        subsystem_id="model_intelligence",
        batch=1,
        state=IntegrationState.READY,
        release_gate="model_intelligence_release_gate",
        evidence_digest="b" * 64,
        approval_boundary_preserved=True,
        external_side_effects_performed=True,
    )
    with pytest.raises(IntegrationError, match="must not perform external side effects"):
        item.normalized()
