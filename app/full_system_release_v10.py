from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FullSystemReleaseCase:
    family: str
    pytest_node_id: str


MANDATORY_FULL_SYSTEM_FAMILIES = (
    FullSystemReleaseCase(
        "subsystem_completeness",
        "tests/test_full_system_integration_v10.py::test_full_system_gate_requires_every_v10_subsystem",
    ),
    FullSystemReleaseCase(
        "integrated_ready_path",
        "tests/test_full_system_integration_v10.py::test_full_system_gate_passes_only_when_all_subsystems_are_ready",
    ),
    FullSystemReleaseCase(
        "blocked_subsystem_fail_closed",
        "tests/test_full_system_integration_v10.py::test_blocked_subsystem_prevents_integrated_readiness",
    ),
    FullSystemReleaseCase(
        "approval_boundary_preservation",
        "tests/test_full_system_integration_v10.py::test_approval_boundary_regression_prevents_integrated_readiness",
    ),
    FullSystemReleaseCase(
        "evidence_identity_integrity",
        "tests/test_full_system_integration_v10.py::test_duplicate_or_unexpected_subsystems_fail_closed",
    ),
    FullSystemReleaseCase(
        "non_executing_readiness_evidence",
        "tests/test_full_system_integration_v10.py::test_integration_evidence_cannot_claim_side_effects",
    ),
    FullSystemReleaseCase(
        "early_batch_verified_attestations",
        "tests/test_full_system_acceptance_v10.py::test_early_batch_attestations_cover_batches_one_through_seven_without_side_effects",
    ),
    FullSystemReleaseCase(
        "cross_batch_release_binding",
        "tests/test_full_system_acceptance_v10.py::test_full_system_acceptance_combines_early_verified_merges_and_late_release_payloads",
    ),
    FullSystemReleaseCase(
        "late_release_fail_closed",
        "tests/test_full_system_acceptance_v10.py::test_full_system_acceptance_fails_when_one_late_release_is_not_ready",
    ),
    FullSystemReleaseCase(
        "release_payload_non_authorization",
        "tests/test_full_system_acceptance_v10.py::test_full_system_acceptance_fails_when_late_release_attempts_to_authorize_execution",
    ),
)


def full_system_release_manifest() -> dict[str, str]:
    return {item.family: item.pytest_node_id for item in MANDATORY_FULL_SYSTEM_FAMILIES}


def audit_full_system_release(results: Mapping[str, bool]) -> dict:
    manifest = full_system_release_manifest()
    missing = sorted(set(manifest) - set(results))
    failed = sorted(family for family in manifest if results.get(family) is not True)
    unexpected = sorted(set(results) - set(manifest))
    ready = not missing and not failed and not unexpected and len(results) == len(manifest)
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-15",
        "ready": ready,
        "missing_families": missing,
        "failed_families": failed,
        "unexpected_families": unexpected,
        "passed": sum(1 for family in manifest if results.get(family) is True),
        "required": len(manifest),
    }


__all__ = ["MANDATORY_FULL_SYSTEM_FAMILIES", "audit_full_system_release", "full_system_release_manifest"]
