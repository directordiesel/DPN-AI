from __future__ import annotations

import pytest

from app.full_system_acceptance_v10 import EARLY_BATCH_ATTESTATIONS, early_batch_evidence, evaluate_full_system_acceptance
from app.full_system_integration_v10 import IntegrationError
from app.full_system_release_binding_v10 import BATCH_RELEASE_BINDINGS


def _late_payloads() -> dict[str, dict]:
    return {
        spec.subsystem_id: {
            "schema_version": 1,
            "checkpoint": spec.expected_checkpoint,
            "ready": True,
            "execution_authorized": False,
            "external_side_effects_performed": False,
            "required_test_count": 4,
        }
        for spec in BATCH_RELEASE_BINDINGS
    }


def test_early_batch_attestations_cover_batches_one_through_seven_without_side_effects():
    evidence = early_batch_evidence()
    assert len(evidence) == len(EARLY_BATCH_ATTESTATIONS) == 8
    assert {item.batch for item in evidence} == set(range(1, 8))
    assert all(item.external_side_effects_performed is False for item in evidence)
    assert all(item.approval_boundary_preserved for item in evidence)


def test_full_system_acceptance_combines_early_verified_merges_and_late_release_payloads():
    readiness = evaluate_full_system_acceptance(_late_payloads())
    assert readiness.ready is True
    assert readiness.checkpoint == "v10.0.0-batch-15"
    assert len(readiness.admitted_subsystems) == 15
    assert not readiness.missing_subsystems
    assert not readiness.blocked_subsystems
    assert not readiness.approval_boundary_failures


def test_full_system_acceptance_fails_when_one_late_release_is_not_ready():
    payloads = _late_payloads()
    payloads["voice_runtime"]["ready"] = False
    with pytest.raises(IntegrationError, match="not ready"):
        evaluate_full_system_acceptance(payloads)


def test_full_system_acceptance_fails_when_late_release_attempts_to_authorize_execution():
    payloads = _late_payloads()
    payloads["capability_marketplace"]["execution_authorized"] = True
    with pytest.raises(IntegrationError, match="execution authorization"):
        evaluate_full_system_acceptance(payloads)
