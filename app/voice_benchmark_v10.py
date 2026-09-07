from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun
from app.benchmark_readiness_v10 import ReadinessGateResult, evaluate_readiness


VOICE_BENCHMARK_MODEL = "dpn-voice-runtime-v10"
VOICE_REQUIRED_FAMILIES = (
    "voice_first_audio_latency",
    "voice_barge_in_correctness",
    "voice_stale_result_suppression",
    "voice_hands_free_recovery",
    "voice_end_to_end_turn",
)


@dataclass(frozen=True)
class VoiceBenchmarkObservation:
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int = 0

    def to_run(self) -> BenchmarkRun:
        if self.task_family not in VOICE_REQUIRED_FAMILIES:
            raise ValueError(f"unsupported voice benchmark family: {self.task_family}")
        return BenchmarkRun(
            model_name=VOICE_BENCHMARK_MODEL,
            task_family=self.task_family,
            task_id=self.task_id,
            passed=self.passed,
            quality_score=self.quality_score,
            latency_ms=self.latency_ms,
        ).normalized()


def voice_runs(observations: Iterable[VoiceBenchmarkObservation]) -> list[BenchmarkRun]:
    return [observation.to_run() for observation in observations]


def evaluate_voice_readiness(runs: Iterable[BenchmarkRun]) -> ReadinessGateResult:
    summaries = BenchmarkLaboratory.summarize(
        run for run in runs if run.model_name == VOICE_BENCHMARK_MODEL
    )
    return evaluate_readiness(
        summaries,
        required_task_families=VOICE_REQUIRED_FAMILIES,
        minimum_success_rate=1.0,
        minimum_quality_score=1.0,
        minimum_samples=1,
    )


__all__ = [
    "VOICE_BENCHMARK_MODEL",
    "VOICE_REQUIRED_FAMILIES",
    "VoiceBenchmarkObservation",
    "evaluate_voice_readiness",
    "voice_runs",
]
