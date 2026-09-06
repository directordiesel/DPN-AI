from pathlib import Path

import pytest

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun, BenchmarkSummary
from app.model_routing_v9 import ModelRoutingError


def test_append_load_and_profile_round_trip(tmp_path: Path) -> None:
    lab = BenchmarkLaboratory(tmp_path / "benchmarks.jsonl")
    lab.append(BenchmarkRun("local-a", "reasoning", "task-1", True, 0.9, 120, retries=1, token_usage=50))
    lab.append(BenchmarkRun("local-a", "reasoning", "task-2", False, 0.6, 180, retries=0, token_usage=30))

    runs = lab.load()
    assert len(runs) == 2

    profiles = lab.profiles()
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.model_name == "local-a"
    assert profile.task_family == "reasoning"
    assert profile.sample_count == 2
    assert profile.success_rate == 0.5
    assert profile.median_latency_ms == 150
    assert profile.quality_score == pytest.approx(0.75)


def test_summaries_group_by_model_and_task_family() -> None:
    summaries = BenchmarkLaboratory.summarize(
        [
            BenchmarkRun("a", "code", "1", True, 1.0, 100),
            BenchmarkRun("a", "code", "2", True, 0.8, 200),
            BenchmarkRun("b", "code", "1", False, 0.4, 300),
            BenchmarkRun("a", "vision", "1", True, 0.7, 400),
        ]
    )
    assert [(item.model_name, item.task_family, item.samples) for item in summaries] == [
        ("a", "code", 2),
        ("a", "vision", 1),
        ("b", "code", 1),
    ]


def test_regression_detection_flags_threshold_drop() -> None:
    baseline = [BenchmarkSummary("a", "code", 100, 90, 0.90, 0.9, 100, 0, None)]
    current = [BenchmarkSummary("a", "code", 100, 82, 0.82, 0.8, 110, 0, None)]

    signals = BenchmarkLaboratory.regressions(baseline, current, threshold=0.05)
    assert len(signals) == 1
    assert signals[0].regressed is True
    assert signals[0].delta == pytest.approx(-0.08)


def test_regression_detection_ignores_new_model_family() -> None:
    baseline = [BenchmarkSummary("a", "code", 10, 9, 0.9, 0.9, 100, 0, None)]
    current = [BenchmarkSummary("b", "code", 10, 9, 0.9, 0.9, 100, 0, None)]
    assert BenchmarkLaboratory.regressions(baseline, current) == []


def test_invalid_jsonl_record_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "benchmarks.jsonl"
    path.write_text('{"bad": true}\n', encoding="utf-8")
    lab = BenchmarkLaboratory(path)

    with pytest.raises(ModelRoutingError, match="invalid benchmark record"):
        lab.load()


def test_invalid_threshold_is_rejected() -> None:
    with pytest.raises(ModelRoutingError, match="threshold"):
        BenchmarkLaboratory.regressions([], [], threshold=1.1)
