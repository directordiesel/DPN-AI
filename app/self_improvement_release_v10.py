from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SelfImprovementReleaseFamily:
    family: str
    pytest_node_id: str


MANDATORY_SELF_IMPROVEMENT_FAMILIES = (
    SelfImprovementReleaseFamily(
        "benchmark_gate",
        "tests/test_self_improvement_v10.py::test_candidate_passes_only_with_complete_non_regressing_benchmark_evidence",
    ),
    SelfImprovementReleaseFamily(
        "commit_binding",
        "tests/test_self_improvement_governance_v10.py::test_application_request_is_approval_only_and_exactly_commit_bound",
    ),
    SelfImprovementReleaseFamily(
        "application_approval_boundary",
        "tests/test_self_improvement_governance_v10.py::test_application_requires_durable_evaluation",
    ),
    SelfImprovementReleaseFamily(
        "rollback_approval_boundary",
        "tests/test_self_improvement_governance_v10.py::test_rollback_is_approval_only",
    ),
)


def self_improvement_release_manifest() -> dict[str, str]:
    return {item.family: item.pytest_node_id for item in MANDATORY_SELF_IMPROVEMENT_FAMILIES}


def audit_self_improvement_release(results: Mapping[str, bool]) -> dict:
    manifest = self_improvement_release_manifest()
    missing = sorted(set(manifest) - set(results))
    failed = sorted(family for family in manifest if results.get(family) is not True)
    unexpected = sorted(set(results) - set(manifest))
    ready = not missing and not failed and not unexpected and len(results) == len(manifest)
    return {
        "schema_version": 1,
        "ready": ready,
        "required_families": sorted(manifest),
        "missing_families": missing,
        "failed_families": failed,
        "unexpected_families": unexpected,
        "passed": sum(1 for family in manifest if results.get(family) is True),
        "required": len(manifest),
    }


__all__ = ["MANDATORY_SELF_IMPROVEMENT_FAMILIES", "audit_self_improvement_release", "self_improvement_release_manifest"]
