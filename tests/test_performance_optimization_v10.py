import pytest

from app.benchmark_laboratory_v10 import BenchmarkRun
from app.performance_optimization_v10 import (
    PerformanceOptimizationError,
    PerformanceOptimizationEvaluator,
    PerformanceOptimizationPolicy,
)


def _run(
    task_id: str,
    *,
    family: str = "reasoning",
    passed: bool = True,
    quality: float = 1.0,
    latency: int = 100,
    retries: int = 0,
    tokens: int | None = 100,
) -> BenchmarkRun:
    return BenchmarkRun(
        model_name="dpn-model",
        task_family=family,
        task_id=task_id,
        passed=passed,
        quality_score=quality,
        latency_ms=latency,
        retries=retries,
        token_usage=tokens,
        created_at="2026-09-07T20:00:00+00:00",
    )


def test_accepts_real_latency_improvement_without_quality_regression():
    evaluator = PerformanceOptimizationEvaluator()
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a", latency=120), _run("b", latency=100)],
        candidate_runs=[_run("a", latency=80), _run("b", latency=70)],
    )

    assert result.gate_passed is True
    assert result.measurable_improvement is True
    assert result.execution_authorized is False
    assert result.families[0].candidate_median_latency_ms < result.families[0].baseline_median_latency_ms


def test_rejects_task_omission_benchmark_gaming():
    evaluator = PerformanceOptimizationEvaluator()
    with pytest.raises(PerformanceOptimizationError, match="task-set mismatch"):
        evaluator.evaluate(
            candidate_id="candidate-a",
            model_name="dpn-model",
            required_task_families=["reasoning"],
            baseline_runs=[_run("easy"), _run("hard", latency=500)],
            candidate_runs=[_run("easy", latency=20)],
        )


def test_rejects_duplicate_task_evidence():
    evaluator = PerformanceOptimizationEvaluator()
    with pytest.raises(PerformanceOptimizationError, match="duplicate benchmark task_id"):
        evaluator.evaluate(
            candidate_id="candidate-a",
            model_name="dpn-model",
            required_task_families=["reasoning"],
            baseline_runs=[_run("same"), _run("same")],
            candidate_runs=[_run("same", latency=50)],
        )


def test_faster_candidate_cannot_trade_away_quality():
    evaluator = PerformanceOptimizationEvaluator()
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a", latency=200)],
        candidate_runs=[_run("a", latency=20, quality=0.99)],
    )

    assert result.gate_passed is False
    assert "minimum_quality_score" in result.families[0].failures
    assert "quality_regression" in result.families[0].failures


def test_faster_candidate_cannot_trade_away_success():
    evaluator = PerformanceOptimizationEvaluator()
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a", latency=200)],
        candidate_runs=[_run("a", latency=20, passed=False)],
    )

    assert result.gate_passed is False
    assert "minimum_success_rate" in result.families[0].failures
    assert "success_regression" in result.families[0].failures


def test_rejects_retry_regression_even_when_latency_improves():
    evaluator = PerformanceOptimizationEvaluator()
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a", latency=200, retries=0)],
        candidate_runs=[_run("a", latency=100, retries=1)],
    )

    assert result.gate_passed is False
    assert "retry_regression" in result.families[0].failures


def test_rejects_token_regression_even_when_latency_improves():
    evaluator = PerformanceOptimizationEvaluator()
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a", latency=200, tokens=100)],
        candidate_runs=[_run("a", latency=100, tokens=101)],
    )

    assert result.gate_passed is False
    assert "token_regression" in result.families[0].failures


def test_requires_measurable_improvement_by_default():
    evaluator = PerformanceOptimizationEvaluator()
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a")],
        candidate_runs=[_run("a")],
    )

    assert result.measurable_improvement is False
    assert result.gate_passed is False


def test_token_evidence_must_be_complete_or_absent():
    evaluator = PerformanceOptimizationEvaluator()
    with pytest.raises(PerformanceOptimizationError, match="token evidence must be complete"):
        evaluator.evaluate(
            candidate_id="candidate-a",
            model_name="dpn-model",
            required_task_families=["reasoning"],
            baseline_runs=[_run("a", tokens=100), _run("b", tokens=None)],
            candidate_runs=[_run("a", tokens=90), _run("b", tokens=90)],
        )


def test_zero_resource_baseline_fails_closed_on_growth():
    policy = PerformanceOptimizationPolicy(minimum_quality_score=1.0, minimum_success_rate=1.0)
    evaluator = PerformanceOptimizationEvaluator(policy=policy)
    result = evaluator.evaluate(
        candidate_id="candidate-a",
        model_name="dpn-model",
        required_task_families=["reasoning"],
        baseline_runs=[_run("a", latency=0, retries=0, tokens=0)],
        candidate_runs=[_run("a", latency=1, retries=0, tokens=0)],
    )

    assert result.gate_passed is False
    assert "latency_regression" in result.families[0].failures


def test_policy_validation_is_strict():
    with pytest.raises(PerformanceOptimizationError):
        PerformanceOptimizationEvaluator(
            policy=PerformanceOptimizationPolicy(max_latency_regression_ratio=float("nan"))
        )
    with pytest.raises(PerformanceOptimizationError):
        PerformanceOptimizationEvaluator(
            policy=PerformanceOptimizationPolicy(require_measurable_improvement=1)  # type: ignore[arg-type]
        )
