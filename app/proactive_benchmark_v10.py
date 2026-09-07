from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun
from app.benchmark_readiness_v10 import ReadinessGateResult, evaluate_readiness


PROACTIVE_BENCHMARK_MODEL = "dpn-proactive-runtime-v10"
PROACTIVE_REQUIRED_FAMILIES = (
    "proactive_trusted_source_integrity",
    "proactive_lifecycle_recovery",
    "proactive_duplicate_suppression",
    "proactive_approval_boundary",
    "proactive_mission_connector_sources",
)


@dataclass(frozen=True)
class ProactiveBenchmarkObservation:
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int = 0

    def to_run(self) -> BenchmarkRun:
        if self.task_family not in PROACTIVE_REQUIRED_FAMILIES:
            raise ValueError(f"unsupported proactive benchmark family: {self.task_family}")
        return BenchmarkRun(
            model_name=PROACTIVE_BENCHMARK_MODEL,
            task_family=self.task_family,
            task_id=self.task_id,
            passed=self.passed,
            quality_score=self.quality_score,
            latency_ms=self.latency_ms,
        ).normalized()


def proactive_runs(observations: Iterable[ProactiveBenchmarkObservation]) -> list[BenchmarkRun]:
    return [item.to_run() for item in observations]


def evaluate_proactive_readiness(runs: Iterable[BenchmarkRun]) -> ReadinessGateResult:
    summaries = BenchmarkLaboratory.summarize(run for run in runs if run.model_name == PROACTIVE_BENCHMARK_MODEL)
    return evaluate_readiness(
        summaries,
        required_task_families=PROACTIVE_REQUIRED_FAMILIES,
        minimum_success_rate=1.0,
        minimum_quality_score=1.0,
        minimum_samples=1,
    )


__all__ = [
    "PROACTIVE_BENCHMARK_MODEL",
    "PROACTIVE_REQUIRED_FAMILIES",
    "ProactiveBenchmarkObservation",
    "evaluate_proactive_readiness",
    "proactive_runs",
]
