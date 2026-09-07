from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class PerformanceReleaseError(ValueError):
    """Raised when Batch 17 release evidence is incomplete or ambiguous."""


@dataclass(frozen=True)
class PerformanceReleaseFamily:
    family: str
    test_id: str
    description: str


_REQUIRED_FAMILIES: tuple[PerformanceReleaseFamily, ...] = (
    PerformanceReleaseFamily(
        "measurable_improvement_integrity",
        "tests/test_performance_optimization_v10.py::test_accepts_real_latency_improvement_without_quality_regression",
        "A release candidate must demonstrate a real measurable resource improvement while preserving correctness and quality.",
    ),
    PerformanceReleaseFamily(
        "benchmark_task_set_integrity",
        "tests/test_performance_optimization_v10.py::test_rejects_task_omission_benchmark_gaming",
        "Baseline and candidate benchmark task sets must match exactly so optimization cannot be manufactured by omitting hard cases.",
    ),
    PerformanceReleaseFamily(
        "quality_success_preservation",
        "tests/test_performance_optimization_v10.py::test_faster_candidate_cannot_trade_away_quality",
        "A faster candidate cannot trade away benchmark quality; the default optimization contract remains fail closed.",
    ),
    PerformanceReleaseFamily(
        "resource_regression_integrity",
        "tests/test_performance_optimization_v10.py::test_rejects_token_regression_even_when_latency_improves",
        "Latency wins cannot hide token/resource regressions outside the governed budget.",
    ),
    PerformanceReleaseFamily(
        "durable_evidence_integrity",
        "tests/test_performance_evidence_v10.py::test_conflicting_duplicate_candidate_digest_fails_closed",
        "Durable optimization receipts must reject conflicting evidence under one candidate digest.",
    ),
    PerformanceReleaseFamily(
        "non_authorizing_evidence",
        "tests/test_performance_evidence_v10.py::test_authorizing_receipt_fails_closed",
        "Performance evidence must never grant execution authorization.",
    ),
    PerformanceReleaseFamily(
        "governed_profile_integrity",
        "tests/test_performance_profiles_v10.py::test_profiles_are_valid_and_non_authorizing_policies",
        "Host-owned performance profiles must remain valid, explicit, and require measurable improvement.",
    ),
)


def performance_release_manifest() -> dict[str, str]:
    return {item.family: item.test_id for item in _REQUIRED_FAMILIES}


def performance_release_families() -> tuple[PerformanceReleaseFamily, ...]:
    return _REQUIRED_FAMILIES


def audit_performance_release(evidence: Mapping[str, object]) -> dict:
    manifest = performance_release_manifest()
    unexpected = sorted(set(evidence) - set(manifest))
    missing = [family for family in manifest if family not in evidence]
    failed = [family for family in manifest if evidence.get(family) is not True]
    ready = not unexpected and not missing and not failed
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-17",
        "ready": ready,
        "required_families": list(manifest),
        "required_test_ids": list(manifest.values()),
        "missing_families": missing,
        "failed_families": failed,
        "unexpected_families": unexpected,
        "execution_authorized": False,
    }


def require_performance_release(evidence: Mapping[str, object]) -> dict:
    audit = audit_performance_release(evidence)
    if not audit["ready"]:
        raise PerformanceReleaseError("Batch 17 performance release evidence is incomplete or failed")
    return audit


__all__ = [
    "PerformanceReleaseError",
    "PerformanceReleaseFamily",
    "audit_performance_release",
    "performance_release_families",
    "performance_release_manifest",
    "require_performance_release",
]
