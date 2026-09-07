from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.specialist_benchmark_v10 import (
    SPECIALIST_REQUIRED_FAMILIES,
    SpecialistBenchmarkObservation,
    evaluate_specialist_readiness,
    specialist_runs,
)


SPECIALIST_RELEASE_TEST_MANIFEST: Mapping[str, tuple[str, ...]] = {
    "specialist_persistence_recovery": (
        "tests/test_specialist_release_cases_v10.py::test_release_specialist_persistence_recovery",
    ),
    "specialist_capability_isolation": (
        "tests/test_specialist_release_cases_v10.py::test_release_specialist_capability_isolation",
    ),
    "specialist_handoff_integrity": (
        "tests/test_specialist_release_cases_v10.py::test_release_specialist_handoff_integrity",
    ),
    "specialist_mission_integration": (
        "tests/test_specialist_release_cases_v10.py::test_release_specialist_mission_integration",
    ),
    "specialist_approval_boundary": (
        "tests/test_specialist_release_cases_v10.py::test_release_specialist_approval_boundary",
    ),
}


@dataclass(frozen=True)
class SpecialistReleaseAuditResult:
    ready: bool
    reason: str
    required_test_ids: tuple[str, ...]
    missing_test_ids: tuple[str, ...]
    failed_test_ids: tuple[str, ...]
    passing_families: int
    failing_families: tuple[str, ...]


def required_specialist_release_test_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                test_id
                for family in SPECIALIST_REQUIRED_FAMILIES
                for test_id in SPECIALIST_RELEASE_TEST_MANIFEST[family]
            }
        )
    )


def audit_specialist_release_evidence(
    *,
    passed_test_ids: Iterable[str],
    failed_test_ids: Iterable[str] = (),
    latency_ms_by_test: Mapping[str, int] | None = None,
) -> SpecialistReleaseAuditResult:
    passed = {str(item).strip() for item in passed_test_ids if str(item).strip()}
    failed = {str(item).strip() for item in failed_test_ids if str(item).strip()}
    required = set(required_specialist_release_test_ids())
    failed_required = tuple(sorted(required.intersection(failed)))
    missing = tuple(sorted(required.difference(passed).difference(failed)))
    latency = dict(latency_ms_by_test or {})

    observations: list[SpecialistBenchmarkObservation] = []
    for family in SPECIALIST_REQUIRED_FAMILIES:
        family_tests = SPECIALIST_RELEASE_TEST_MANIFEST[family]
        family_passed = all(test_id in passed for test_id in family_tests)
        family_failed = any(test_id in failed for test_id in family_tests)
        observations.append(
            SpecialistBenchmarkObservation(
                task_family=family,
                task_id=f"{family}:release-manifest",
                passed=family_passed and not family_failed,
                quality_score=1.0 if family_passed and not family_failed else 0.0,
                latency_ms=max((int(latency.get(test_id, 0)) for test_id in family_tests), default=0),
            )
        )

    readiness = evaluate_specialist_readiness(specialist_runs(observations))
    ready = readiness.ready and not missing and not failed_required
    if failed_required:
        reason = "specialist release audit failed: required tests failed"
    elif missing:
        reason = "specialist release audit failed closed: required executed-test evidence is missing"
    elif not readiness.ready:
        reason = "specialist release audit failed closed: specialist benchmark gate did not pass"
    else:
        reason = "specialist release audit passed"

    return SpecialistReleaseAuditResult(
        ready=ready,
        reason=reason,
        required_test_ids=tuple(sorted(required)),
        missing_test_ids=missing,
        failed_test_ids=failed_required,
        passing_families=readiness.passing_profiles,
        failing_families=readiness.failing_profiles,
    )


__all__ = [
    "SPECIALIST_RELEASE_TEST_MANIFEST",
    "SpecialistReleaseAuditResult",
    "audit_specialist_release_evidence",
    "required_specialist_release_test_ids",
]
