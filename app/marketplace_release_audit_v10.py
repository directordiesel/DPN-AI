from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from app.marketplace_benchmark_v10 import (
    MARKETPLACE_REQUIRED_FAMILIES,
    MarketplaceBenchmarkObservation,
    evaluate_marketplace_readiness,
    marketplace_runs,
)

MARKETPLACE_RELEASE_TEST_MANIFEST: Mapping[str, tuple[str, ...]] = {
    "marketplace_package_integrity": (
        "tests/test_capability_marketplace_v10.py::test_marketplace_inspection_is_digest_bound_and_never_executes_code",
    ),
    "marketplace_publisher_signature": (
        "tests/test_marketplace_trust_v10.py::test_package_signature_and_catalog_membership_are_verified",
    ),
    "marketplace_catalog_membership": (
        "tests/test_marketplace_trust_v10.py::test_expired_catalog_and_duplicate_versions_fail_closed",
    ),
    "marketplace_tool_contract": (
        "tests/test_marketplace_trust_v10.py::test_live_tool_contract_rejects_missing_tools_and_risk_escalation",
        "tests/test_marketplace_trust_v10.py::test_live_tool_contract_is_non_authorizing_when_exact",
    ),
    "marketplace_approval_boundary": (
        "tests/test_capability_marketplace_plugin_v10.py::test_marketplace_plugin_preserves_high_risk_activation_boundary",
        "tests/test_capability_marketplace_v10.py::test_marketplace_promotion_uses_forge_and_preserves_evidence",
    ),
}

@dataclass(frozen=True)
class MarketplaceReleaseAuditResult:
    ready: bool
    reason: str
    required_test_ids: tuple[str, ...]
    missing_test_ids: tuple[str, ...]
    failed_test_ids: tuple[str, ...]
    passing_families: int
    failing_families: tuple[str, ...]


def required_marketplace_release_test_ids() -> tuple[str, ...]:
    return tuple(sorted({test_id for family in MARKETPLACE_REQUIRED_FAMILIES for test_id in MARKETPLACE_RELEASE_TEST_MANIFEST[family]}))


def audit_marketplace_release_evidence(*, passed_test_ids: Iterable[str], failed_test_ids: Iterable[str] = (), latency_ms_by_test: Mapping[str, int] | None = None) -> MarketplaceReleaseAuditResult:
    passed = {str(item).strip() for item in passed_test_ids if str(item).strip()}
    failed = {str(item).strip() for item in failed_test_ids if str(item).strip()}
    required = set(required_marketplace_release_test_ids())
    failed_required = tuple(sorted(required.intersection(failed)))
    missing = tuple(sorted(required.difference(passed).difference(failed)))
    latency = dict(latency_ms_by_test or {})
    observations = []
    for family in MARKETPLACE_REQUIRED_FAMILIES:
        tests = MARKETPLACE_RELEASE_TEST_MANIFEST[family]
        family_passed = all(test_id in passed for test_id in tests)
        family_failed = any(test_id in failed for test_id in tests)
        observations.append(MarketplaceBenchmarkObservation(task_family=family, task_id=f"{family}:release-manifest", passed=family_passed and not family_failed, quality_score=1.0 if family_passed and not family_failed else 0.0, latency_ms=max((int(latency.get(test_id, 0)) for test_id in tests), default=0)))
    readiness = evaluate_marketplace_readiness(marketplace_runs(observations))
    ready = readiness.ready and not missing and not failed_required
    if failed_required:
        reason = "marketplace release audit failed: required tests failed"
    elif missing:
        reason = "marketplace release audit failed closed: required executed-test evidence is missing"
    elif not readiness.ready:
        reason = "marketplace release audit failed closed: marketplace benchmark gate did not pass"
    else:
        reason = "marketplace release audit passed"
    return MarketplaceReleaseAuditResult(ready=ready, reason=reason, required_test_ids=tuple(sorted(required)), missing_test_ids=missing, failed_test_ids=failed_required, passing_families=readiness.passing_profiles, failing_families=readiness.failing_profiles)

__all__ = ["MARKETPLACE_RELEASE_TEST_MANIFEST", "MarketplaceReleaseAuditResult", "audit_marketplace_release_evidence", "required_marketplace_release_test_ids"]
