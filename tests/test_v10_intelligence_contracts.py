import pytest

from core.v10_intelligence_contracts import (
    BenchmarkCaseResult,
    IntelligenceModelSelector,
    IntelligenceRequest,
    Modality,
    ModelCandidate,
    NoEligibleModelError,
    TaskDifficulty,
    summarize_benchmarks,
)


def _candidate(
    model_id: str,
    *,
    local: bool = True,
    healthy: bool = True,
    modalities=frozenset({Modality.TEXT, Modality.CODE}),
    capabilities=frozenset({"reasoning", "coding"}),
    benchmark_score: float = 0.8,
    latency: int = 1000,
    cost: float = 0.0,
):
    return ModelCandidate(
        model_id=model_id,
        provider="test",
        local=local,
        healthy=healthy,
        modalities=modalities,
        capabilities=capabilities,
        benchmark_score=benchmark_score,
        estimated_latency_ms=latency,
        estimated_cost_units=cost,
    )


def test_selector_prefers_higher_verified_quality():
    request = IntelligenceRequest(
        task_id="code-1",
        intent="repair repository bug",
        difficulty=TaskDifficulty.HIGH,
        modalities=frozenset({Modality.TEXT, Modality.CODE}),
        required_capabilities=frozenset({"coding"}),
    )
    result = IntelligenceModelSelector().select(
        request,
        [_candidate("small", benchmark_score=0.60), _candidate("strong", benchmark_score=0.92)],
    )
    assert result.selected_model_id == "strong"


def test_selector_fails_closed_when_privacy_blocks_remote_models():
    request = IntelligenceRequest(
        task_id="private-1",
        intent="analyze confidential source",
        difficulty=TaskDifficulty.MEDIUM,
        privacy_required=True,
    )
    with pytest.raises(NoEligibleModelError):
        IntelligenceModelSelector().select(
            request,
            [_candidate("remote", local=False)],
        )


def test_selector_records_rejection_evidence():
    request = IntelligenceRequest(
        task_id="vision-1",
        intent="inspect screenshot",
        difficulty=TaskDifficulty.MEDIUM,
        modalities=frozenset({Modality.IMAGE}),
    )
    result = IntelligenceModelSelector().select(
        request,
        [
            _candidate("text-only", modalities=frozenset({Modality.TEXT})),
            _candidate("vision", modalities=frozenset({Modality.TEXT, Modality.IMAGE})),
        ],
    )
    assert result.selected_model_id == "vision"
    assert result.rejected["text-only"] == ("missing_modality",)


def test_benchmark_summary_reports_domain_and_success_metrics():
    summary = summarize_benchmarks(
        [
            BenchmarkCaseResult("c1", "coding", True, 1.0, 100),
            BenchmarkCaseResult("c2", "coding", False, 0.5, 300),
            BenchmarkCaseResult("r1", "research", True, 0.75, 200),
        ]
    )
    assert summary.total_cases == 3
    assert summary.successful_cases == 2
    assert summary.success_rate == pytest.approx(2 / 3, abs=1e-6)
    assert summary.mean_score == pytest.approx(0.75)
    assert summary.mean_latency_ms == pytest.approx(200.0)
    assert summary.by_domain == {"coding": 0.75, "research": 0.75}


def test_contract_validation_rejects_invalid_budget_and_scores():
    with pytest.raises(ValueError):
        IntelligenceRequest(
            task_id="x",
            intent="x",
            difficulty=TaskDifficulty.LOW,
            max_latency_ms=0,
        )
    with pytest.raises(ValueError):
        _candidate("bad", benchmark_score=1.1)
