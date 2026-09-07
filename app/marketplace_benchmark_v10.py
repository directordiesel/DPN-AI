from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun
from app.benchmark_readiness_v10 import ReadinessGateResult, evaluate_readiness

MARKETPLACE_BENCHMARK_MODEL = "dpn-capability-marketplace-v10"
MARKETPLACE_REQUIRED_FAMILIES = (
    "marketplace_package_integrity",
    "marketplace_publisher_signature",
    "marketplace_catalog_membership",
    "marketplace_tool_contract",
    "marketplace_approval_boundary",
)

@dataclass(frozen=True)
class MarketplaceBenchmarkObservation:
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int = 0

    def to_run(self) -> BenchmarkRun:
        if self.task_family not in MARKETPLACE_REQUIRED_FAMILIES:
            raise ValueError(f"unsupported marketplace benchmark family: {self.task_family}")
        return BenchmarkRun(
            model_name=MARKETPLACE_BENCHMARK_MODEL,
            task_family=self.task_family,
            task_id=self.task_id,
            passed=self.passed,
            quality_score=self.quality_score,
            latency_ms=self.latency_ms,
        ).normalized()


def marketplace_runs(observations: Iterable[MarketplaceBenchmarkObservation]) -> list[BenchmarkRun]:
    return [item.to_run() for item in observations]


def evaluate_marketplace_readiness(runs: Iterable[BenchmarkRun]) -> ReadinessGateResult:
    summaries = BenchmarkLaboratory.summarize(run for run in runs if run.model_name == MARKETPLACE_BENCHMARK_MODEL)
    return evaluate_readiness(
        summaries,
        required_task_families=MARKETPLACE_REQUIRED_FAMILIES,
        minimum_success_rate=1.0,
        minimum_quality_score=1.0,
        minimum_samples=1,
    )

__all__ = ["MARKETPLACE_BENCHMARK_MODEL", "MARKETPLACE_REQUIRED_FAMILIES", "MarketplaceBenchmarkObservation", "evaluate_marketplace_readiness", "marketplace_runs"]
