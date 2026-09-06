from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from app.model_routing_v9 import ModelCandidate, ModelCapability, ModelRoutingError, ProviderClass


class TaskDifficulty(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class PrivacyMode(str, Enum):
    LOCAL_ONLY = "local_only"
    PREFER_LOCAL = "prefer_local"
    REMOTE_ALLOWED = "remote_allowed"


@dataclass(frozen=True)
class BenchmarkProfile:
    model_name: str
    task_family: str
    success_rate: float
    sample_count: int
    median_latency_ms: int | None = None
    quality_score: float | None = None

    def validate(self) -> None:
        if not self.model_name.strip():
            raise ModelRoutingError("benchmark model name is required")
        if not self.task_family.strip():
            raise ModelRoutingError("benchmark task family is required")
        if isinstance(self.success_rate, bool) or not isinstance(self.success_rate, (int, float)):
            raise ModelRoutingError("benchmark success rate must be numeric")
        if not math.isfinite(float(self.success_rate)) or not 0.0 <= float(self.success_rate) <= 1.0:
            raise ModelRoutingError("benchmark success rate must be between 0 and 1")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 1:
            raise ModelRoutingError("benchmark sample count must be a positive integer")
        if self.median_latency_ms is not None and (
            isinstance(self.median_latency_ms, bool)
            or not isinstance(self.median_latency_ms, int)
            or self.median_latency_ms < 0
        ):
            raise ModelRoutingError("benchmark latency must be a non-negative integer")
        if self.quality_score is not None:
            if isinstance(self.quality_score, bool) or not isinstance(self.quality_score, (int, float)):
                raise ModelRoutingError("benchmark quality score must be numeric")
            if not math.isfinite(float(self.quality_score)) or not 0.0 <= float(self.quality_score) <= 1.0:
                raise ModelRoutingError("benchmark quality score must be between 0 and 1")


@dataclass(frozen=True)
class IntelligenceRequest:
    task_family: str
    required_capabilities: frozenset[ModelCapability] = field(default_factory=lambda: frozenset({ModelCapability.CHAT}))
    difficulty: TaskDifficulty = TaskDifficulty.MEDIUM
    privacy_mode: PrivacyMode = PrivacyMode.PREFER_LOCAL
    max_latency_ms: int | None = None
    max_cost_weight: float | None = None
    minimum_success_rate: float = 0.0
    minimum_samples: int = 1

    def validate(self) -> None:
        if not self.task_family.strip():
            raise ModelRoutingError("task family is required")
        if not self.required_capabilities:
            raise ModelRoutingError("at least one required capability is required")
        if self.max_latency_ms is not None and (
            isinstance(self.max_latency_ms, bool)
            or not isinstance(self.max_latency_ms, int)
            or self.max_latency_ms < 0
        ):
            raise ModelRoutingError("max latency must be a non-negative integer")
        if self.max_cost_weight is not None:
            if isinstance(self.max_cost_weight, bool) or not isinstance(self.max_cost_weight, (int, float)):
                raise ModelRoutingError("max cost weight must be numeric")
            if not math.isfinite(float(self.max_cost_weight)) or float(self.max_cost_weight) < 0:
                raise ModelRoutingError("max cost weight must be finite and non-negative")
        if isinstance(self.minimum_success_rate, bool) or not isinstance(self.minimum_success_rate, (int, float)):
            raise ModelRoutingError("minimum success rate must be numeric")
        if not math.isfinite(float(self.minimum_success_rate)) or not 0.0 <= float(self.minimum_success_rate) <= 1.0:
            raise ModelRoutingError("minimum success rate must be between 0 and 1")
        if isinstance(self.minimum_samples, bool) or not isinstance(self.minimum_samples, int) or self.minimum_samples < 1:
            raise ModelRoutingError("minimum samples must be a positive integer")


@dataclass(frozen=True)
class IntelligenceDecision:
    selected: ModelCandidate
    benchmark: BenchmarkProfile
    score: float
    reason: str


class ModelIntelligenceEngine:
    """Benchmark-backed, fail-closed model selection for DPN AI v10.

    The engine does not probe providers, bypass network policy, or invent benchmark
    evidence. It only ranks candidates that already satisfy discovered capability,
    health, privacy, latency, cost and benchmark requirements.
    """

    _difficulty_weight = {
        TaskDifficulty.LOW: 0.70,
        TaskDifficulty.MEDIUM: 0.82,
        TaskDifficulty.HIGH: 0.92,
        TaskDifficulty.EXTREME: 1.00,
    }

    def decide(
        self,
        candidates: Iterable[ModelCandidate],
        benchmarks: Iterable[BenchmarkProfile],
        request: IntelligenceRequest,
    ) -> IntelligenceDecision:
        request.validate()

        benchmark_map: dict[str, BenchmarkProfile] = {}
        for benchmark in benchmarks:
            benchmark.validate()
            if benchmark.task_family == request.task_family:
                existing = benchmark_map.get(benchmark.model_name)
                if existing is None or benchmark.sample_count > existing.sample_count:
                    benchmark_map[benchmark.model_name] = benchmark

        eligible: list[tuple[ModelCandidate, BenchmarkProfile]] = []
        for candidate in candidates:
            candidate.validate()
            if not candidate.healthy:
                continue
            if not request.required_capabilities.issubset(candidate.capabilities):
                continue
            if request.privacy_mode == PrivacyMode.LOCAL_ONLY and candidate.provider_class != ProviderClass.LOCAL:
                continue
            if request.max_latency_ms is not None and (
                candidate.latency_ms is None or candidate.latency_ms > request.max_latency_ms
            ):
                continue
            if request.max_cost_weight is not None and float(candidate.cost_weight) > float(request.max_cost_weight):
                continue
            benchmark = benchmark_map.get(candidate.name)
            if benchmark is None:
                continue
            if benchmark.sample_count < request.minimum_samples:
                continue
            if float(benchmark.success_rate) < float(request.minimum_success_rate):
                continue
            eligible.append((candidate, benchmark))

        if not eligible:
            raise ModelRoutingError("no model satisfies v10 intelligence and benchmark requirements")

        def score(item: tuple[ModelCandidate, BenchmarkProfile]) -> tuple[float, int, str]:
            candidate, benchmark = item
            quality = benchmark.quality_score if benchmark.quality_score is not None else candidate.quality_score
            difficulty_target = self._difficulty_weight[request.difficulty]
            benchmark_strength = min(1.0, benchmark.sample_count / 100.0)
            locality_bonus = 0.03 if (
                request.privacy_mode == PrivacyMode.PREFER_LOCAL
                and candidate.provider_class == ProviderClass.LOCAL
            ) else 0.0
            latency_penalty = 0.0
            observed_latency = benchmark.median_latency_ms if benchmark.median_latency_ms is not None else candidate.latency_ms
            if observed_latency is not None:
                latency_penalty = min(0.15, observed_latency / 100_000.0)
            cost_penalty = min(0.15, float(candidate.cost_weight) * 0.02)
            combined = (
                float(benchmark.success_rate) * 0.48
                + float(quality) * 0.24
                + float(candidate.health_score) * 0.13
                + benchmark_strength * 0.10
                + locality_bonus
                - latency_penalty
                - cost_penalty
            )
            if float(benchmark.success_rate) < difficulty_target:
                combined -= (difficulty_target - float(benchmark.success_rate)) * 0.35
            return (-combined, candidate.priority, candidate.name.lower())

        ordered = sorted(eligible, key=score)
        selected, benchmark = ordered[0]
        final_score = -score(ordered[0])[0]
        reason = (
            f"selected by v10 benchmark-backed intelligence routing for {request.task_family}; "
            f"difficulty={request.difficulty.value}, privacy={request.privacy_mode.value}, "
            f"success_rate={benchmark.success_rate:.3f}, samples={benchmark.sample_count}"
        )
        return IntelligenceDecision(selected=selected, benchmark=benchmark, score=final_score, reason=reason)


__all__ = [
    "BenchmarkProfile",
    "IntelligenceDecision",
    "IntelligenceRequest",
    "ModelIntelligenceEngine",
    "PrivacyMode",
    "TaskDifficulty",
]
