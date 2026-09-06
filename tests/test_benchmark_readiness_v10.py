from app.benchmark_readiness_v10 import (
    BenchmarkReadinessError,
    build_leaderboard,
    evaluate_readiness,
)
from app.benchmark_laboratory_v10 import BenchmarkSummary


def summary(model: str, family: str, success: float, quality: float, samples: int, latency: int = 500):
    passed = round(success * samples)
    return BenchmarkSummary(
        model_name=model,
        task_family=family,
        samples=samples,
        passed=passed,
        success_rate=success,
        mean_quality_score=quality,
        median_latency_ms=latency,
        total_retries=0,
        total_token_usage=100,
    )


def test_leaderboard_ranks_stronger_model_first():
    board = build_leaderboard([
        summary("weak", "reasoning", 0.72, 0.70, 30, 400),
        summary("strong", "reasoning", 0.92, 0.90, 60, 600),
    ])
    assert [entry.model_name for entry in board] == ["strong", "weak"]
    assert board[0].rank == 1


def test_readiness_passes_when_each_required_family_has_strong_evidence():
    result = evaluate_readiness(
        [
            summary("m1", "reasoning", 0.90, 0.88, 40),
            summary("m2", "coding", 0.87, 0.82, 35),
        ],
        required_task_families=["reasoning", "coding"],
    )
    assert result.ready is True
    assert result.passing_profiles == 2
    assert result.failing_profiles == ()


def test_readiness_fails_closed_on_missing_family():
    result = evaluate_readiness(
        [summary("m1", "reasoning", 0.90, 0.88, 40)],
        required_task_families=["reasoning", "coding"],
    )
    assert result.ready is False
    assert "coding:missing" in result.failing_profiles


def test_readiness_fails_for_low_samples_success_or_quality():
    result = evaluate_readiness(
        [summary("m1", "reasoning", 0.70, 0.60, 5)],
        required_task_families=["reasoning"],
    )
    assert result.ready is False
    assert result.failing_profiles == ("reasoning:samples,success_rate,quality_score",)


def test_readiness_uses_best_model_per_task_family():
    result = evaluate_readiness(
        [
            summary("weak", "reasoning", 0.65, 0.60, 30),
            summary("strong", "reasoning", 0.95, 0.92, 50),
        ],
        required_task_families=["reasoning"],
    )
    assert result.ready is True


def test_invalid_thresholds_are_rejected():
    try:
        evaluate_readiness([], required_task_families=["reasoning"], minimum_success_rate=1.1)
    except BenchmarkReadinessError:
        pass
    else:
        raise AssertionError("expected invalid success-rate threshold to fail")

    try:
        evaluate_readiness([], required_task_families=["reasoning"], minimum_samples=0)
    except BenchmarkReadinessError:
        pass
    else:
        raise AssertionError("expected invalid sample threshold to fail")


def test_required_task_family_is_mandatory():
    try:
        evaluate_readiness([], required_task_families=[])
    except BenchmarkReadinessError:
        pass
    else:
        raise AssertionError("expected empty readiness scope to fail")
