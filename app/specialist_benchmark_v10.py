from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun
from app.benchmark_readiness_v10 import ReadinessGateResult, evaluate_readiness


SPECIALIST_BENCHMARK_MODEL = "dpn-specialist-organization-v10"
SPECIALIST_REQUIRED_FAMILIES = (
    "specialist_persistence_recovery",
    "specialist_capability_isolation",
    "specialist_handoff_integrity",
    "specialist_mission_integration",
    "specialist_approval_boundary",
)


@dataclass(frozen=True)
class SpecialistBenchmarkObservation:
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int = 0

    def to_run(self) -> BenchmarkRun:
        if self.task_family not in SPECIALIST_REQUIRED_FAMILIES:
            raise ValueError(f"unsupported specialist benchmark family: {self.task_family}")
        return BenchmarkRun(
            model_name=SPECIALIST_BENCHMARK_MODEL,
            task_family=self.task_family,
            task_id=self.task_id,
            passed=self.passed,
            quality_score=self.quality_score,
            latency_ms=self.latency_ms,
        ).normalized()


def specialist_runs(observations: Iterable[SpecialistBenchmarkObservation]) -> list[BenchmarkRun]:
    return [observation.to_run() for observation in observations]


def evaluate_specialist_readiness(runs: Iterable[BenchmarkRun]) -> ReadinessGateResult:
    summaries = BenchmarkLaboratory.summarize(
        run for run in runs if run.model_name == SPECIALIST_BENCHMARK_MODEL
    )
    return evaluate_readiness(
        summaries,
        required_task_families=SPECIALIST_REQUIRED_FAMILIES,
        minimum_success_rate=1.0,
        minimum_quality_score=1.0,
        minimum_samples=1,
    )


__all__ = [
    "SPECIALIST_BENCHMARK_MODEL",
    "SPECIALIST_REQUIRED_FAMILIES",
    "SpecialistBenchmarkObservation",
    "evaluate_specialist_readiness",
    "specialist_runs",
]
