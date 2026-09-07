from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ProductionReleaseGateError(ValueError):
    """Raised when Batch 18 release-readiness evidence is incomplete."""


@dataclass(frozen=True)
class ProductionReleaseFamily:
    family: str
    test_id: str
    description: str


_REQUIRED_FAMILIES: tuple[ProductionReleaseFamily, ...] = (
    ProductionReleaseFamily(
        "stable_version_identity",
        "tests/test_production_release_v10.py::test_release_target_version_is_exact",
        "Stable promotion must target exactly DPN AI v10.0.0.",
    ),
    ProductionReleaseFamily(
        "exact_commit_binding",
        "tests/test_production_release_v10.py::test_release_candidate_requires_exact_commit_identity",
        "Release evidence must bind one exact lowercase 40-character commit SHA.",
    ),
    ProductionReleaseFamily(
        "validation_gate_integrity",
        "tests/test_production_release_v10.py::test_missing_or_unexpected_gate_evidence_fails_closed",
        "The release candidate must contain the exact governed validation-gate set.",
    ),
    ProductionReleaseFamily(
        "strict_gate_boolean_integrity",
        "tests/test_production_release_v10.py::test_failed_or_truthy_non_boolean_gate_evidence_fails_closed",
        "Failed or merely truthy gate evidence must not satisfy release readiness.",
    ),
    ProductionReleaseFamily(
        "release_artifact_contract",
        "tests/test_production_release_v10.py::test_release_artifact_contract_is_exact_and_complete",
        "Stable release preparation requires the complete governed source/SBOM/checksum artifact contract.",
    ),
    ProductionReleaseFamily(
        "immutable_release_target",
        "tests/test_production_release_v10.py::test_existing_release_target_is_immutable",
        "An already-published v10.0.0 target cannot be overwritten or reused.",
    ),
    ProductionReleaseFamily(
        "non_authorizing_release_evidence",
        "tests/test_production_release_v10.py::test_complete_release_candidate_is_ready_but_non_authorizing",
        "Release-readiness evidence never grants execution or publication authority.",
    ),
    ProductionReleaseFamily(
        "deterministic_commit_bound_evidence",
        "tests/test_production_release_v10.py::test_evidence_digest_is_deterministic_and_commit_bound",
        "Release evidence must be deterministic and cryptographically bound to the exact candidate commit.",
    ),
    ProductionReleaseFamily(
        "active_version_surface_coherence",
        "tests/test_version_promotion_v10.py::test_active_version_surfaces_are_exact_and_non_authorizing",
        "All active product version surfaces must agree on v10.0.0 while historical v9 evidence remains outside promotion scope.",
    ),
)


def production_release_manifest() -> dict[str, str]:
    return {item.family: item.test_id for item in _REQUIRED_FAMILIES}


def production_release_families() -> tuple[ProductionReleaseFamily, ...]:
    return _REQUIRED_FAMILIES


def audit_production_release_gate(evidence: Mapping[str, object]) -> dict:
    manifest = production_release_manifest()
    missing = [family for family in manifest if family not in evidence]
    unexpected = sorted(set(evidence) - set(manifest))
    failed = [family for family in manifest if evidence.get(family) is not True]
    ready = not missing and not unexpected and not failed
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-18-production-readiness",
        "ready": ready,
        "required_families": list(manifest),
        "required_test_ids": list(manifest.values()),
        "missing_families": missing,
        "failed_families": failed,
        "unexpected_families": unexpected,
        "execution_authorized": False,
        "release_publish_authorized": False,
    }


def require_production_release_gate(evidence: Mapping[str, object]) -> dict:
    audit = audit_production_release_gate(evidence)
    if not audit["ready"]:
        raise ProductionReleaseGateError("Batch 18 production release evidence is incomplete or failed")
    return audit


__all__ = [
    "ProductionReleaseFamily",
    "ProductionReleaseGateError",
    "audit_production_release_gate",
    "production_release_families",
    "production_release_manifest",
    "require_production_release_gate",
]
