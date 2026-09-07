from pathlib import Path

import pytest

from app.benchmark_laboratory_v10 import BenchmarkRun
from app.performance_evidence_v10 import PerformanceEvidenceStore
from app.performance_optimization_v10 import (
    PerformanceOptimizationError,
    PerformanceOptimizationEvaluator,
)


def _run(task_id: str, latency: int, *, tokens: int = 100) -> BenchmarkRun:
    return BenchmarkRun(
        model_name="dpn-test",
        task_family="voice",
        task_id=task_id,
        passed=True,
        quality_score=1.0,
        latency_ms=latency,
        retries=0,
        token_usage=tokens,
        created_at="2026-09-07T20:00:00+00:00",
    )


def _evaluation():
    return PerformanceOptimizationEvaluator().evaluate(
        candidate_id="candidate-1",
        model_name="dpn-test",
        required_task_families=["voice"],
        baseline_runs=[_run("a", 100), _run("b", 120)],
        candidate_runs=[_run("a", 80), _run("b", 90)],
    )


def test_durable_receipt_round_trip_and_idempotent_replay(tmp_path: Path) -> None:
    store = PerformanceEvidenceStore(tmp_path / "performance.jsonl")
    evaluation = _evaluation()
    first = store.record(evaluation)
    second = store.record(evaluation)
    assert first == second
    assert len(store.load()) == 1
    assert first.gate_passed is True
    assert first.execution_authorized is False


def test_corrupt_receipt_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "performance.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(PerformanceOptimizationError):
        PerformanceEvidenceStore(path).load()


def test_authorizing_receipt_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "performance.jsonl"
    path.write_text(
        '{"schema_version":1,"candidate_id":"x","candidate_digest":"d","model_name":"m","required_families":["voice"],"gate_passed":true,"measurable_improvement":true,"evaluation_digest":"e","execution_authorized":true}\n',
        encoding="utf-8",
    )
    with pytest.raises(PerformanceOptimizationError):
        PerformanceEvidenceStore(path).load()
