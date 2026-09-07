from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping


class ProductionReleaseError(ValueError):
    """Raised when Batch 18 stable-release evidence is incomplete or unsafe."""


EXPECTED_STABLE_VERSION = "10.0.0"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_VALIDATION_GATES: tuple[str, ...] = (
    "ci",
    "security_gate_v2",
    "runtime_recovery_assurance",
    "repository_health",
    "batch_8_memory",
    "batch_9_artifacts",
    "batch_10_voice",
    "batch_11_proactive",
    "batch_12_specialist",
    "batch_13_marketplace",
    "batch_14_self_improvement",
    "batch_15_full_system_integration",
    "batch_16_security_regression",
    "batch_17_performance",
)

REQUIRED_RELEASE_ARTIFACTS: tuple[str, ...] = (
    "source_archive",
    "sha256s",
    "release_manifest",
    "sbom_spdx",
    "source_sha256s",
    "dependency_inventory",
)


@dataclass(frozen=True)
class ProductionReleaseEvaluation:
    schema_version: int
    target_version: str
    target_tag: str
    commit_sha: str
    required_validation_gates: tuple[str, ...]
    required_release_artifacts: tuple[str, ...]
    evidence_digest: str
    ready_for_version_promotion: bool
    ready_for_release_dispatch: bool
    execution_authorized: bool = False
    release_publish_authorized: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["required_validation_gates"] = list(self.required_validation_gates)
        payload["required_release_artifacts"] = list(self.required_release_artifacts)
        return payload


def _require_exact_true_mapping(
    evidence: Mapping[str, object], *, required: tuple[str, ...], label: str
) -> dict[str, bool]:
    if not isinstance(evidence, Mapping):
        raise ProductionReleaseError(f"{label} evidence must be a mapping")
    actual = set(evidence)
    expected = set(required)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ProductionReleaseError(
            f"{label} evidence must contain the exact governed set; missing={missing}, unexpected={unexpected}"
        )
    normalized: dict[str, bool] = {}
    for key in required:
        value = evidence[key]
        if type(value) is not bool:
            raise ProductionReleaseError(f"{label} evidence for {key} must be an exact boolean")
        if value is not True:
            raise ProductionReleaseError(f"{label} evidence failed closed for {key}")
        normalized[key] = True
    return normalized


def evaluate_production_release(
    *,
    target_version: str,
    commit_sha: str,
    validation_gates: Mapping[str, object],
    release_artifacts: Mapping[str, object],
    release_already_published: bool = False,
) -> ProductionReleaseEvaluation:
    """Evaluate stable-release evidence without granting publication authority."""

    if not isinstance(target_version, str) or target_version != EXPECTED_STABLE_VERSION:
        raise ProductionReleaseError(
            f"stable release target must be exactly {EXPECTED_STABLE_VERSION}"
        )
    if (
        not isinstance(commit_sha, str)
        or commit_sha != commit_sha.strip()
        or _COMMIT_RE.fullmatch(commit_sha) is None
    ):
        raise ProductionReleaseError("release candidate must bind an exact lowercase 40-character commit SHA")
    if type(release_already_published) is not bool:
        raise ProductionReleaseError("release_already_published must be an exact boolean")
    if release_already_published:
        raise ProductionReleaseError("stable release target already exists; releases are immutable")

    gates = _require_exact_true_mapping(
        validation_gates, required=REQUIRED_VALIDATION_GATES, label="validation gate"
    )
    artifacts = _require_exact_true_mapping(
        release_artifacts, required=REQUIRED_RELEASE_ARTIFACTS, label="release artifact"
    )

    payload = {
        "schema_version": 1,
        "target_version": EXPECTED_STABLE_VERSION,
        "target_tag": f"v{EXPECTED_STABLE_VERSION}",
        "commit_sha": commit_sha,
        "validation_gates": gates,
        "release_artifacts": artifacts,
        "release_already_published": False,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return ProductionReleaseEvaluation(
        schema_version=1,
        target_version=EXPECTED_STABLE_VERSION,
        target_tag=f"v{EXPECTED_STABLE_VERSION}",
        commit_sha=commit_sha,
        required_validation_gates=REQUIRED_VALIDATION_GATES,
        required_release_artifacts=REQUIRED_RELEASE_ARTIFACTS,
        evidence_digest=digest,
        ready_for_version_promotion=True,
        ready_for_release_dispatch=True,
        execution_authorized=False,
        release_publish_authorized=False,
    )


__all__ = [
    "EXPECTED_STABLE_VERSION",
    "ProductionReleaseError",
    "ProductionReleaseEvaluation",
    "REQUIRED_RELEASE_ARTIFACTS",
    "REQUIRED_VALIDATION_GATES",
    "evaluate_production_release",
]
