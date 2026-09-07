from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkRun, BenchmarkSummary
from app.benchmark_readiness_v10 import ReadinessGateResult, evaluate_readiness


MEMORY_BENCHMARK_MODEL = "dpn-memory-runtime-v10"
MEMORY_REQUIRED_FAMILIES = (
    "memory_scope_isolation",
    "memory_provenance_integrity",
    "memory_conflict_preservation",
    "memory_supersession_lineage",
    "memory_recovery_detection",
    "memory_retention_bounds",
    "memory_trusted_promotion",
    "memory_tool_authorization",
)


@dataclass(frozen=True)
class MemoryBenchmarkObservation:
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int
    retries: int = 0

    def to_run(self) -> BenchmarkRun:
        family = self.task_family.strip()
        if family not in MEMORY_REQUIRED_FAMILIES:
            raise ValueError(f"unsupported memory benchmark family: {family}")
        task_id = self.task_id.strip()
        if not task_id:
            raise ValueError("memory benchmark task id is required")
        return BenchmarkRun(
            model_name=MEMORY_BENCHMARK_MODEL,
            task_family=family,
            task_id=task_id,
            passed=bool(self.passed),
            quality_score=self.quality_score,
            latency_ms=self.latency_ms,
            retries=self.retries,
            token_usage=None,
        ).normalized()


@dataclass(frozen=True)
class MemoryReadinessResult:
    ready: bool
    reason: str
    required_families: tuple[str, ...]
    passing_families: int
    failing_families: tuple[str, ...]
    evaluated_samples: int
    overall_success_rate: float
    overall_quality_score: float


def memory_runs(observations: Iterable[MemoryBenchmarkObservation]) -> tuple[BenchmarkRun, ...]:
    return tuple(item.to_run() for item in observations)


def evaluate_memory_readiness(summaries: Iterable[BenchmarkSummary]) -> MemoryReadinessResult:
    relevant = [
        item
        for item in summaries
        if item.model_name == MEMORY_BENCHMARK_MODEL and item.task_family in MEMORY_REQUIRED_FAMILIES
    ]
    gate: ReadinessGateResult = evaluate_readiness(
        relevant,
        required_task_families=MEMORY_REQUIRED_FAMILIES,
        minimum_success_rate=1.0,
        minimum_quality_score=1.0,
        minimum_samples=1,
    )

    sample_count = sum(item.samples for item in relevant)
    passed_count = sum(item.passed for item in relevant)
    weighted_quality = sum(item.mean_quality_score * item.samples for item in relevant)
    success_rate = passed_count / sample_count if sample_count else 0.0
    quality_score = weighted_quality / sample_count if sample_count else 0.0

    return MemoryReadinessResult(
        ready=gate.ready,
        reason=(
            "memory benchmark readiness gate passed"
            if gate.ready
            else "memory benchmark readiness gate failed closed"
        ),
        required_families=MEMORY_REQUIRED_FAMILIES,
        passing_families=gate.passing_profiles,
        failing_families=gate.failing_profiles,
        evaluated_samples=sample_count,
        overall_success_rate=success_rate,
        overall_quality_score=quality_score,
    )


__all__ = [
    "MEMORY_BENCHMARK_MODEL",
    "MEMORY_REQUIRED_FAMILIES",
    "MemoryBenchmarkObservation",
    "MemoryReadinessResult",
    "evaluate_memory_readiness",
    "memory_runs",
]
