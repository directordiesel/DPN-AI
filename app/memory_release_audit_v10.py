from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.benchmark_laboratory_v10 import BenchmarkLaboratory
from app.memory_benchmark_v10 import (
    MEMORY_REQUIRED_FAMILIES,
    MemoryBenchmarkObservation,
    MemoryReadinessResult,
    evaluate_memory_readiness,
    memory_runs,
)


MEMORY_RELEASE_TEST_MANIFEST: Mapping[str, tuple[str, ...]] = {
    "memory_scope_isolation": (
        "tests/test_advanced_layered_memory_v10.py::test_user_recall_cannot_see_another_user_namespace",
        "tests/test_advanced_layered_memory_v10.py::test_layer_scope_mismatch_rejects_before_storage",
    ),
    "memory_provenance_integrity": (
        "tests/test_advanced_layered_memory_v10.py::test_project_fact_delegates_to_existing_memory_service_with_typed_provenance",
        "tests/test_advanced_layered_memory_v10.py::test_derived_and_inference_memory_require_evidence_before_any_write",
    ),
    "memory_conflict_preservation": (
        "tests/test_advanced_layered_memory_v10.py::test_conflicting_versions_are_preserved_and_recall_reports_conflict",
    ),
    "memory_supersession_lineage": (
        "tests/test_memory_lineage_v10.py::test_supersession_preserves_old_version_and_writes_immutable_lineage_receipt",
        "tests/test_memory_lineage_v10.py::test_lower_authority_replacement_cannot_supersede_stronger_memory",
    ),
    "memory_recovery_detection": (
        "tests/test_memory_compaction_v10.py::test_cross_lineage_receipt_is_ignored_and_flagged_for_recovery",
        "tests/test_memory_compaction_v10.py::test_cycle_is_detected_and_cycle_nodes_are_not_marked_superseded",
    ),
    "memory_retention_bounds": (
        "tests/test_advanced_layered_memory_v10.py::test_working_memory_is_bounded_expiring_and_scope_isolated",
    ),
    "memory_trusted_promotion": (
        "tests/test_advanced_layered_memory_v10.py::test_semantic_default_does_not_promote_conversation_scope_into_long_term_semantic_memory",
        "tests/test_advanced_layered_memory_v10.py::test_existing_version_verification_failure_blocks_persistent_mutation",
    ),
    "memory_tool_authorization": (
        "tests/test_memory_tools_v10.py::test_supersession_forces_human_approval_even_when_policy_allows",
        "tests/test_memory_tools_v10.py::test_supersession_boundary_never_overrides_a_hard_deny",
        "tests/test_memory_tools_v10.py::test_non_global_scope_fails_closed_without_host_authorizer",
    ),
}


@dataclass(frozen=True)
class MemoryReleaseAuditResult:
    ready: bool
    reason: str
    readiness: MemoryReadinessResult
    required_test_ids: tuple[str, ...]
    missing_test_ids: tuple[str, ...]
    failed_test_ids: tuple[str, ...]


def required_memory_release_test_ids() -> tuple[str, ...]:
    return tuple(
        sorted({test_id for family in MEMORY_REQUIRED_FAMILIES for test_id in MEMORY_RELEASE_TEST_MANIFEST[family]})
    )


def audit_memory_release_evidence(
    *,
    passed_test_ids: Iterable[str],
    failed_test_ids: Iterable[str] = (),
    latency_ms_by_test: Mapping[str, int] | None = None,
) -> MemoryReleaseAuditResult:
    """Convert trusted executed-test evidence into the strict Batch 8 readiness gate.

    The caller must supply test identities from a trusted test runner/CI adapter. This
    function never assumes that a test passed merely because it exists in the repo.
    Any required failure or missing required test fails closed.
    """

    passed = {item.strip() for item in passed_test_ids if item and item.strip()}
    failed = {item.strip() for item in failed_test_ids if item and item.strip()}
    required = set(required_memory_release_test_ids())

    failed_required = tuple(sorted(required.intersection(failed)))
    missing = tuple(sorted(required.difference(passed).difference(failed)))

    observations: list[MemoryBenchmarkObservation] = []
    latency_map = dict(latency_ms_by_test or {})
    for family in MEMORY_REQUIRED_FAMILIES:
        family_tests = MEMORY_RELEASE_TEST_MANIFEST[family]
        family_passed = all(test_id in passed for test_id in family_tests)
        family_failed = any(test_id in failed for test_id in family_tests)
        observations.append(
            MemoryBenchmarkObservation(
                task_family=family,
                task_id=f"{family}:release-manifest",
                passed=family_passed and not family_failed,
                quality_score=1.0 if family_passed and not family_failed else 0.0,
                latency_ms=max((latency_map.get(test_id, 0) for test_id in family_tests), default=0),
            )
        )

    summaries = BenchmarkLaboratory.summarize(memory_runs(observations))
    readiness = evaluate_memory_readiness(summaries)
    ready = readiness.ready and not missing and not failed_required
    if failed_required:
        reason = "memory release audit failed: required tests failed"
    elif missing:
        reason = "memory release audit failed closed: required executed-test evidence is missing"
    elif not readiness.ready:
        reason = "memory release audit failed closed: benchmark gate did not pass"
    else:
        reason = "memory release audit passed"

    return MemoryReleaseAuditResult(
        ready=ready,
        reason=reason,
        readiness=readiness,
        required_test_ids=tuple(sorted(required)),
        missing_test_ids=missing,
        failed_test_ids=failed_required,
    )


__all__ = [
    "MEMORY_RELEASE_TEST_MANIFEST",
    "MemoryReleaseAuditResult",
    "audit_memory_release_evidence",
    "required_memory_release_test_ids",
]
