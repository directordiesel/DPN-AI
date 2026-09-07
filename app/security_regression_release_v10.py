from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class SecurityRegressionReleaseError(ValueError):
    """Raised when Batch 16 release evidence is incomplete or ambiguous."""


@dataclass(frozen=True)
class SecurityRegressionReleaseFamily:
    family: str
    test_id: str
    description: str


_REQUIRED_FAMILIES: tuple[SecurityRegressionReleaseFamily, ...] = (
    SecurityRegressionReleaseFamily(
        "benchmark_evidence_integrity",
        "tests/test_benchmark_laboratory_v10.py::test_passed_requires_real_boolean",
        "Benchmark pass/fail evidence must be a real boolean and cannot rely on truthy coercion.",
    ),
    SecurityRegressionReleaseFamily(
        "repository_path_containment",
        "tests/test_coding_repository_intelligence_v10.py::test_repository_map_rejects_cross_platform_alias_and_device_paths",
        "Repository evidence must reject cross-platform aliases, device names, control characters, and alternate streams.",
    ),
    SecurityRegressionReleaseFamily(
        "ci_terminal_state_integrity",
        "tests/test_coding_ci_orchestrator_v10.py::test_every_non_success_terminal_ci_conclusion_fails_closed",
        "Only an explicit successful required CI job may contribute readiness evidence.",
    ),
    SecurityRegressionReleaseFamily(
        "model_provider_provenance",
        "tests/test_model_intelligence_v10.py::test_unbound_benchmark_cannot_cross_bind_same_name_across_providers",
        "Ambiguous same-name models across providers must not share unbound benchmark evidence.",
    ),
    SecurityRegressionReleaseFamily(
        "connector_risk_contract",
        "tests/test_dpn_connector_protocol_v10.py::test_connector_boolean_state_and_approval_fields_are_strict",
        "Connector state and approval metadata must use strict typed evidence instead of truthy caller values.",
    ),
    SecurityRegressionReleaseFamily(
        "approval_payload_binding",
        "tests/test_approval_payload_security.py::test_tampered_encrypted_payload_is_denied_before_execution",
        "Approved execution must be cryptographically bound to the exact deferred payload and tool contract.",
    ),
    SecurityRegressionReleaseFamily(
        "approval_exact_reauthorization",
        "tests/test_approval_payload_security.py::test_execution_reauthorizes_exact_decrypted_arguments",
        "Approval execution must re-run authorization over the exact decrypted arguments immediately before invoke.",
    ),
)


def security_regression_release_manifest() -> dict[str, str]:
    return {item.family: item.test_id for item in _REQUIRED_FAMILIES}


def security_regression_release_families() -> tuple[SecurityRegressionReleaseFamily, ...]:
    return _REQUIRED_FAMILIES


def audit_security_regression_release(evidence: Mapping[str, object]) -> dict:
    manifest = security_regression_release_manifest()
    unexpected = sorted(set(evidence) - set(manifest))
    missing = [family for family in manifest if family not in evidence]
    failed = [family for family in manifest if evidence.get(family) is not True]
    ready = not unexpected and not missing and not failed
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-16",
        "ready": ready,
        "required_families": list(manifest),
        "required_test_ids": list(manifest.values()),
        "missing_families": missing,
        "failed_families": failed,
        "unexpected_families": unexpected,
        "execution_authorized": False,
    }


def require_security_regression_release(evidence: Mapping[str, object]) -> dict:
    audit = audit_security_regression_release(evidence)
    if not audit["ready"]:
        raise SecurityRegressionReleaseError("Batch 16 security/regression release evidence is incomplete or failed")
    return audit


__all__ = [
    "SecurityRegressionReleaseError",
    "SecurityRegressionReleaseFamily",
    "audit_security_regression_release",
    "require_security_regression_release",
    "security_regression_release_families",
    "security_regression_release_manifest",
]
