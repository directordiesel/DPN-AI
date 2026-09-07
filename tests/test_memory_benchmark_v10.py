from __future__ import annotations

import pytest

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun
from app.memory_benchmark_v10 import (
    MEMORY_BENCHMARK_MODEL,
    MEMORY_REQUIRED_FAMILIES,
    MemoryBenchmarkObservation,
    evaluate_memory_readiness,
    memory_runs,
)


def _passing_observations():
    return [
        MemoryBenchmarkObservation(
            task_family=family,
            task_id=f"{family}:baseline",
            passed=True,
            quality_score=1.0,
            latency_ms=1,
        )
        for family in MEMORY_REQUIRED_FAMILIES
    ]


def test_memory_benchmark_uses_existing_laboratory_contract():
    runs = memory_runs(_passing_observations())
    assert len(runs) == len(MEMORY_REQUIRED_FAMILIES)
    assert all(isinstance(item, BenchmarkRun) for item in runs)
    assert all(item.model_name == MEMORY_BENCHMARK_MODEL for item in runs)
    assert {item.task_family for item in runs} == set(MEMORY_REQUIRED_FAMILIES)


def test_complete_perfect_memory_evidence_is_ready():
    summaries = BenchmarkLaboratory.summarize(memory_runs(_passing_observations()))
    result = evaluate_memory_readiness(summaries)
    assert result.ready is True
    assert result.passing_families == len(MEMORY_REQUIRED_FAMILIES)
    assert result.failing_families == ()
    assert result.evaluated_samples == len(MEMORY_REQUIRED_FAMILIES)
    assert result.overall_success_rate == 1.0
    assert result.overall_quality_score == 1.0


def test_missing_critical_family_fails_closed():
    observations = _passing_observations()[:-1]
    summaries = BenchmarkLaboratory.summarize(memory_runs(observations))
    result = evaluate_memory_readiness(summaries)
    assert result.ready is False
    assert any(entry.endswith(":missing") for entry in result.failing_families)


def test_one_failure_cannot_be_averaged_away():
    observations = _passing_observations()
    family = MEMORY_REQUIRED_FAMILIES[0]
    observations.append(
        MemoryBenchmarkObservation(
            task_family=family,
            task_id=f"{family}:adversarial",
            passed=False,
            quality_score=0.0,
            latency_ms=1,
        )
    )
    summaries = BenchmarkLaboratory.summarize(memory_runs(observations))
    result = evaluate_memory_readiness(summaries)
    assert result.ready is False
    assert any(entry.startswith(f"{family}:") for entry in result.failing_families)
    assert result.overall_success_rate < 1.0


def test_quality_regression_blocks_readiness_even_when_case_passes():
    observations = _passing_observations()
    family = MEMORY_REQUIRED_FAMILIES[1]
    observations[1] = MemoryBenchmarkObservation(
        task_family=family,
        task_id=f"{family}:weak-evidence",
        passed=True,
        quality_score=0.99,
        latency_ms=1,
    )
    summaries = BenchmarkLaboratory.summarize(memory_runs(observations))
    result = evaluate_memory_readiness(summaries)
    assert result.ready is False
    assert f"{family}:quality_score" in result.failing_families


def test_unknown_family_and_invalid_observation_fail_before_evidence_creation():
    with pytest.raises(ValueError, match="unsupported memory benchmark family"):
        MemoryBenchmarkObservation("memory_unknown", "case", True, 1.0, 1).to_run()
    with pytest.raises(ValueError, match="task id"):
        MemoryBenchmarkObservation(MEMORY_REQUIRED_FAMILIES[0], " ", True, 1.0, 1).to_run()
