from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.artifact_benchmark_v10 import (
    ARTIFACT_REQUIRED_FAMILIES,
    ArtifactBenchmarkObservation,
    artifact_runs,
    evaluate_artifact_readiness,
)


ARTIFACT_RELEASE_TEST_MANIFEST: Mapping[str, tuple[str, ...]] = {
    "artifact_docx_professional": (
        "tests/test_artifact_release_cases_v10.py::test_release_docx_professional_end_to_end",
    ),
    "artifact_pdf_professional": (
        "tests/test_artifact_release_cases_v10.py::test_release_pdf_professional_end_to_end",
    ),
    "artifact_xlsx_professional": (
        "tests/test_artifact_release_cases_v10.py::test_release_xlsx_professional_end_to_end",
    ),
    "artifact_pptx_professional": (
        "tests/test_artifact_release_cases_v10.py::test_release_pptx_professional_end_to_end",
    ),
}


@dataclass(frozen=True)
class ArtifactReleaseAuditResult:
    ready: bool
    reason: str
    required_test_ids: tuple[str, ...]
    missing_test_ids: tuple[str, ...]
    failed_test_ids: tuple[str, ...]
    passing_families: int
    failing_families: tuple[str, ...]


def required_artifact_release_test_ids() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                test_id
                for family in ARTIFACT_REQUIRED_FAMILIES
                for test_id in ARTIFACT_RELEASE_TEST_MANIFEST[family]
            }
        )
    )


def audit_artifact_release_evidence(
    *,
    passed_test_ids: Iterable[str],
    failed_test_ids: Iterable[str] = (),
    latency_ms_by_test: Mapping[str, int] | None = None,
) -> ArtifactReleaseAuditResult:
    passed = {item.strip() for item in passed_test_ids if item and item.strip()}
    failed = {item.strip() for item in failed_test_ids if item and item.strip()}
    required = set(required_artifact_release_test_ids())
    failed_required = tuple(sorted(required.intersection(failed)))
    missing = tuple(sorted(required.difference(passed).difference(failed)))
    latency_map = dict(latency_ms_by_test or {})

    observations: list[ArtifactBenchmarkObservation] = []
    for family in ARTIFACT_REQUIRED_FAMILIES:
        family_tests = ARTIFACT_RELEASE_TEST_MANIFEST[family]
        family_passed = all(test_id in passed for test_id in family_tests)
        family_failed = any(test_id in failed for test_id in family_tests)
        observations.append(
            ArtifactBenchmarkObservation(
                task_family=family,
                task_id=f"{family}:release-manifest",
                passed=family_passed and not family_failed,
                quality_score=1.0 if family_passed and not family_failed else 0.0,
                latency_ms=max((latency_map.get(test_id, 0) for test_id in family_tests), default=0),
            )
        )

    readiness = evaluate_artifact_readiness(artifact_runs(observations))
    ready = readiness.ready and not missing and not failed_required
    if failed_required:
        reason = "artifact release audit failed: required tests failed"
    elif missing:
        reason = "artifact release audit failed closed: required executed-test evidence is missing"
    elif not readiness.ready:
        reason = "artifact release audit failed closed: four-format benchmark gate did not pass"
    else:
        reason = "artifact release audit passed"

    return ArtifactReleaseAuditResult(
        ready=ready,
        reason=reason,
        required_test_ids=tuple(sorted(required)),
        missing_test_ids=missing,
        failed_test_ids=failed_required,
        passing_families=readiness.passing_profiles,
        failing_families=readiness.failing_profiles,
    )


__all__ = [
    "ARTIFACT_RELEASE_TEST_MANIFEST",
    "ArtifactReleaseAuditResult",
    "audit_artifact_release_evidence",
    "required_artifact_release_test_ids",
]
