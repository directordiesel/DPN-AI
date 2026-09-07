from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun
from app.benchmark_readiness_v10 import ReadinessGateResult, evaluate_readiness


ARTIFACT_BENCHMARK_MODEL = "dpn-artifact-runtime-v10"
ARTIFACT_REQUIRED_FAMILIES = (
    "artifact_docx_professional",
    "artifact_pdf_professional",
    "artifact_xlsx_professional",
    "artifact_pptx_professional",
)


@dataclass(frozen=True)
class ArtifactBenchmarkObservation:
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int = 0

    def to_run(self) -> BenchmarkRun:
        if self.task_family not in ARTIFACT_REQUIRED_FAMILIES:
            raise ValueError(f"unsupported artifact benchmark family: {self.task_family}")
        return BenchmarkRun(
            model_name=ARTIFACT_BENCHMARK_MODEL,
            task_family=self.task_family,
            task_id=self.task_id,
            passed=self.passed,
            quality_score=self.quality_score,
            latency_ms=self.latency_ms,
        ).normalized()


def artifact_runs(observations: Iterable[ArtifactBenchmarkObservation]) -> list[BenchmarkRun]:
    return [observation.to_run() for observation in observations]


def evaluate_artifact_readiness(runs: Iterable[BenchmarkRun]) -> ReadinessGateResult:
    summaries = BenchmarkLaboratory.summarize(
        run for run in runs if run.model_name == ARTIFACT_BENCHMARK_MODEL
    )
    return evaluate_readiness(
        summaries,
        required_task_families=ARTIFACT_REQUIRED_FAMILIES,
        minimum_success_rate=1.0,
        minimum_quality_score=1.0,
        minimum_samples=1,
    )


__all__ = [
    "ARTIFACT_BENCHMARK_MODEL",
    "ARTIFACT_REQUIRED_FAMILIES",
    "ArtifactBenchmarkObservation",
    "artifact_runs",
    "evaluate_artifact_readiness",
]
