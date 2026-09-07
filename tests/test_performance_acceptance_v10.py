from dataclasses import replace

import pytest

from app.benchmark_laboratory_v10 import BenchmarkRun
from app.performance_acceptance_v10 import evaluate_cross_profile_acceptance
from app.performance_optimization_v10 import PerformanceOptimizationError, PerformanceOptimizationEvaluator
from app.performance_profiles_v10 import PROFILES


def _run(family: str, latency: int, *, model_name: str = "dpn-platform") -> BenchmarkRun:
    return BenchmarkRun(
        model_name=model_name,
        task_family=family,
        task_id=f"{family}-required",
        passed=True,
        quality_score=1.0,
        latency_ms=latency,
        retries=0,
        token_usage=100,
        created_at="2026-09-07T20:00:00+00:00",
    )


def _evaluations(candidate_id: str = "candidate-v10"):
    result = {}
    for profile_id, profile in PROFILES.items():
        evaluator = PerformanceOptimizationEvaluator(policy=profile.policy)
        baseline = [_run(family, 100) for family in profile.required_families]
        candidate = [_run(family, 80) for family in profile.required_families]
        result[profile_id] = evaluator.evaluate(
            candidate_id=candidate_id,
            model_name="dpn-platform",
            required_task_families=profile.required_families,
            baseline_runs=baseline,
            candidate_runs=candidate,
        )
    return result


def test_cross_profile_acceptance_binds_all_profiles_to_one_candidate_and_model() -> None:
    result = evaluate_cross_profile_acceptance(_evaluations())
    assert result.accepted is True
    assert result.execution_authorized is False
    assert result.candidate_id == "candidate-v10"
    assert result.model_name == "dpn-platform"
    assert result.required_profiles == tuple(sorted(PROFILES))
    assert len(result.evaluation_digests) == len(PROFILES)
    assert len(result.acceptance_digest) == 64


def test_cross_profile_acceptance_rejects_missing_profile() -> None:
    evaluations = _evaluations()
    evaluations.pop("interactive_latency")
    with pytest.raises(PerformanceOptimizationError, match="exact governed profile set"):
        evaluate_cross_profile_acceptance(evaluations)


def test_cross_profile_acceptance_rejects_mixed_candidate_identity() -> None:
    evaluations = _evaluations()
    evaluations["agent_efficiency"] = replace(
        evaluations["agent_efficiency"], candidate_id="different-candidate"
    )
    with pytest.raises(PerformanceOptimizationError, match="one candidate identity"):
        evaluate_cross_profile_acceptance(evaluations)


def test_cross_profile_acceptance_rejects_profile_family_drift() -> None:
    evaluations = _evaluations()
    evaluations["interactive_latency"] = replace(
        evaluations["interactive_latency"], required_families=("voice",)
    )
    with pytest.raises(PerformanceOptimizationError, match="does not match governed profile"):
        evaluate_cross_profile_acceptance(evaluations)


def test_cross_profile_acceptance_rejects_non_passing_profile() -> None:
    evaluations = _evaluations()
    evaluations["balanced_platform"] = replace(
        evaluations["balanced_platform"], gate_passed=False
    )
    with pytest.raises(PerformanceOptimizationError, match="governed performance profile failed"):
        evaluate_cross_profile_acceptance(evaluations)
