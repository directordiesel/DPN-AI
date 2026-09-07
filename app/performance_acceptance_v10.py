from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Mapping

from app.performance_optimization_v10 import (
    PerformanceOptimizationError,
    PerformanceOptimizationEvaluation,
)
from app.performance_profiles_v10 import PROFILES


@dataclass(frozen=True)
class PerformanceAcceptanceResult:
    schema_version: int
    candidate_id: str
    model_name: str
    required_profiles: tuple[str, ...]
    evaluation_digests: tuple[str, ...]
    acceptance_digest: str
    accepted: bool
    reason: str
    execution_authorized: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["required_profiles"] = list(self.required_profiles)
        payload["evaluation_digests"] = list(self.evaluation_digests)
        return payload


def evaluate_cross_profile_acceptance(
    evaluations: Mapping[str, PerformanceOptimizationEvaluation],
) -> PerformanceAcceptanceResult:
    required_profiles = tuple(sorted(PROFILES))
    if set(evaluations) != set(required_profiles):
        raise PerformanceOptimizationError("cross-profile acceptance requires the exact governed profile set")

    candidate_ids: set[str] = set()
    model_names: set[str] = set()
    digests: list[str] = []

    for profile_id in required_profiles:
        evaluation = evaluations[profile_id]
        if not isinstance(evaluation, PerformanceOptimizationEvaluation):
            raise PerformanceOptimizationError("cross-profile acceptance requires typed optimization evaluations")
        profile = PROFILES[profile_id]
        profile.validate()
        if evaluation.required_families != tuple(sorted(profile.required_families)):
            raise PerformanceOptimizationError(f"optimization evidence does not match governed profile {profile_id}")
        if evaluation.execution_authorized is not False:
            raise PerformanceOptimizationError("performance evaluation attempted to authorize execution")
        if not evaluation.gate_passed or not evaluation.measurable_improvement:
            raise PerformanceOptimizationError(f"governed performance profile failed: {profile_id}")
        if not evaluation.candidate_id.strip() or not evaluation.model_name.strip() or not evaluation.candidate_digest.strip():
            raise PerformanceOptimizationError("performance evaluation identity evidence is incomplete")
        candidate_ids.add(evaluation.candidate_id)
        model_names.add(evaluation.model_name)
        digests.append(evaluation.candidate_digest)

    if len(candidate_ids) != 1:
        raise PerformanceOptimizationError("cross-profile performance evidence must bind one candidate identity")
    if len(model_names) != 1:
        raise PerformanceOptimizationError("cross-profile performance evidence must bind one model identity")
    if len(set(digests)) != len(digests):
        raise PerformanceOptimizationError("cross-profile performance evidence contains duplicate evaluation digests")

    candidate_id = next(iter(candidate_ids))
    model_name = next(iter(model_names))
    digest_payload = {
        "candidate_id": candidate_id,
        "model_name": model_name,
        "required_profiles": list(required_profiles),
        "evaluation_digests": digests,
    }
    acceptance_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return PerformanceAcceptanceResult(
        schema_version=1,
        candidate_id=candidate_id,
        model_name=model_name,
        required_profiles=required_profiles,
        evaluation_digests=tuple(digests),
        acceptance_digest=acceptance_digest,
        accepted=True,
        reason="all governed performance profiles passed for one candidate/model; execution remains unauthorized",
        execution_authorized=False,
    )


__all__ = ["PerformanceAcceptanceResult", "evaluate_cross_profile_acceptance"]
