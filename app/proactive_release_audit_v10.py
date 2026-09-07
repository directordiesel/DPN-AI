from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.proactive_benchmark_v10 import (
    PROACTIVE_REQUIRED_FAMILIES,
    ProactiveBenchmarkObservation,
    evaluate_proactive_readiness,
    proactive_runs,
)


PROACTIVE_RELEASE_TEST_MANIFEST: Mapping[str, tuple[str, ...]] = {
    "proactive_trusted_source_integrity": (
        "tests/test_proactive_release_cases_v10.py::test_release_trusted_source_integrity",
    ),
    "proactive_lifecycle_recovery": (
        "tests/test_proactive_release_cases_v10.py::test_release_lifecycle_persistence_and_recovery",
    ),
    "proactive_duplicate_suppression": (
        "tests/test_proactive_release_cases_v10.py::test_release_duplicate_suppression",
    ),
    "proactive_approval_boundary": (
        "tests/test_proactive_release_cases_v10.py::test_release_approval_boundary_and_idempotency",
    ),
    "proactive_mission_connector_sources": (
        "tests/test_proactive_release_cases_v10.py::test_release_mission_connector_source_integration",
    ),
}


@dataclass(frozen=True)
class ProactiveReleaseAuditResult:
    ready: bool
    reason: str
    required_test_ids: tuple[str, ...]
    missing_test_ids: tuple[str, ...]
    failed_test_ids: tuple[str, ...]
    passing_families: int
    failing_families: tuple[str, ...]


def required_proactive_release_test_ids() -> tuple[str, ...]:
    return tuple(sorted({test_id for family in PROACTIVE_REQUIRED_FAMILIES for test_id in PROACTIVE_RELEASE_TEST_MANIFEST[family]}))


def audit_proactive_release_evidence(
    *,
    passed_test_ids: Iterable[str],
    failed_test_ids: Iterable[str] = (),
    latency_ms_by_test: Mapping[str, int] | None = None,
) -> ProactiveReleaseAuditResult:
    passed = {str(item).strip() for item in passed_test_ids if str(item).strip()}
    failed = {str(item).strip() for item in failed_test_ids if str(item).strip()}
    required = set(required_proactive_release_test_ids())
    failed_required = tuple(sorted(required.intersection(failed)))
    missing = tuple(sorted(required.difference(passed).difference(failed)))
    latency = dict(latency_ms_by_test or {})

    observations: list[ProactiveBenchmarkObservation] = []
    for family in PROACTIVE_REQUIRED_FAMILIES:
        family_tests = PROACTIVE_RELEASE_TEST_MANIFEST[family]
        family_passed = all(test_id in passed for test_id in family_tests)
        family_failed = any(test_id in failed for test_id in family_tests)
        observations.append(
            ProactiveBenchmarkObservation(
                task_family=family,
                task_id=f"{family}:release-manifest",
                passed=family_passed and not family_failed,
                quality_score=1.0 if family_passed and not family_failed else 0.0,
                latency_ms=max((latency.get(test_id, 0) for test_id in family_tests), default=0),
            )
        )

    readiness = evaluate_proactive_readiness(proactive_runs(observations))
    ready = readiness.ready and not missing and not failed_required
    if failed_required:
        reason = "proactive release audit failed: required tests failed"
    elif missing:
        reason = "proactive release audit failed closed: required executed-test evidence is missing"
    elif not readiness.ready:
        reason = "proactive release audit failed closed: proactive benchmark gate did not pass"
    else:
        reason = "proactive release audit passed"

    return ProactiveReleaseAuditResult(
        ready=ready,
        reason=reason,
        required_test_ids=tuple(sorted(required)),
        missing_test_ids=missing,
        failed_test_ids=failed_required,
        passing_families=readiness.passing_profiles,
        failing_families=readiness.failing_profiles,
    )


__all__ = [
    "PROACTIVE_RELEASE_TEST_MANIFEST",
    "ProactiveReleaseAuditResult",
    "audit_proactive_release_evidence",
    "required_proactive_release_test_ids",
]
