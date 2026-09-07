from __future__ import annotations

import pytest

from app.full_system_integration_v10 import IntegrationError
from app.full_system_release_binding_v10 import BATCH_RELEASE_BINDINGS, FullSystemReleaseBinder


def _payload(checkpoint: str) -> dict:
    return {
        "schema_version": 1,
        "checkpoint": checkpoint,
        "ready": True,
        "execution_authorized": False,
        "external_side_effects_performed": False,
        "required_test_count": 4,
    }


def test_bind_all_requires_exact_batch_8_through_14_release_payloads():
    binder = FullSystemReleaseBinder()
    payloads = {spec.subsystem_id: _payload(spec.expected_checkpoint) for spec in BATCH_RELEASE_BINDINGS}
    evidence = binder.bind_all(payloads)
    assert len(evidence) == 7
    assert {item.batch for item in evidence} == set(range(8, 15))
    assert all(item.approval_boundary_preserved for item in evidence)
    assert all(len(item.evidence_digest) == 64 for item in evidence)


def test_release_payload_checkpoint_mismatch_fails_closed():
    binder = FullSystemReleaseBinder()
    with pytest.raises(IntegrationError, match="checkpoint mismatch"):
        binder.bind("layered_memory", _payload("v10.0.0-batch-9"))


def test_release_payload_cannot_grant_execution_authority():
    binder = FullSystemReleaseBinder()
    payload = _payload("v10.0.0-batch-14")
    payload["execution_authorized"] = True
    with pytest.raises(IntegrationError, match="execution authorization"):
        binder.bind("self_improvement", payload)


def test_release_payload_cannot_claim_external_side_effects():
    binder = FullSystemReleaseBinder()
    payload = _payload("v10.0.0-batch-13")
    payload["external_side_effects_performed"] = True
    with pytest.raises(IntegrationError, match="external side effects"):
        binder.bind("capability_marketplace", payload)


def test_bind_all_rejects_missing_or_unexpected_payloads():
    binder = FullSystemReleaseBinder()
    payloads = {spec.subsystem_id: _payload(spec.expected_checkpoint) for spec in BATCH_RELEASE_BINDINGS}
    payloads.pop("voice_runtime")
    with pytest.raises(IntegrationError, match="missing release payloads"):
        binder.bind_all(payloads)

    payloads = {spec.subsystem_id: _payload(spec.expected_checkpoint) for spec in BATCH_RELEASE_BINDINGS}
    payloads["unknown"] = _payload("v10.0.0-batch-x")
    with pytest.raises(IntegrationError, match="unexpected release payloads"):
        binder.bind_all(payloads)
