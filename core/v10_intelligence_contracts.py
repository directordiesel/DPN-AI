from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping, Sequence


class TaskDifficulty(str, Enum):
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class Modality(str, Enum):
    TEXT = "text"
    CODE = "code"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    PDF = "pdf"
    SPREADSHEET = "spreadsheet"
    SCREENSHOT = "screenshot"


@dataclass(frozen=True)
class IntelligenceRequest:
    task_id: str
    intent: str
    difficulty: TaskDifficulty
    modalities: frozenset[Modality] = field(default_factory=lambda: frozenset({Modality.TEXT}))
    privacy_required: bool = True
    max_latency_ms: int | None = None
    max_cost_units: float | None = None
    required_capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not self.intent.strip():
            raise ValueError("intent must not be empty")
        if self.max_latency_ms is not None and self.max_latency_ms <= 0:
            raise ValueError("max_latency_ms must be positive")
        if self.max_cost_units is not None and self.max_cost_units < 0:
            raise ValueError("max_cost_units must be non-negative")


@dataclass(frozen=True)
class ModelCandidate:
    model_id: str
    provider: str
    local: bool
    healthy: bool
    modalities: frozenset[Modality]
    capabilities: frozenset[str]
    benchmark_score: float
    estimated_latency_ms: int
    estimated_cost_units: float = 0.0

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not 0.0 <= self.benchmark_score <= 1.0:
            raise ValueError("benchmark_score must be between 0 and 1")
        if self.estimated_latency_ms < 0:
            raise ValueError("estimated_latency_ms must be non-negative")
        if self.estimated_cost_units < 0:
            raise ValueError("estimated_cost_units must be non-negative")


@dataclass(frozen=True)
class ModelSelectionEvidence:
    selected_model_id: str
    score: float
    considered_models: tuple[str, ...]
    rejected: Mapping[str, tuple[str, ...]]


class NoEligibleModelError(RuntimeError):
    pass


class IntelligenceModelSelector:
    """Deterministic, fail-closed v10 model selection foundation.

    This class does not call a model provider. It evaluates discovered model
    candidates against explicit capability, privacy, health, latency, cost,
    modality, and benchmark constraints and returns auditable evidence.
    """

    _DIFFICULTY_WEIGHT = {
        TaskDifficulty.TRIVIAL: 0.15,
        TaskDifficulty.LOW: 0.30,
        TaskDifficulty.MEDIUM: 0.55,
        TaskDifficulty.HIGH: 0.80,
        TaskDifficulty.EXTREME: 1.00,
    }

    def select(
        self,
        request: IntelligenceRequest,
        candidates: Iterable[ModelCandidate],
    ) -> ModelSelectionEvidence:
        rejected: dict[str, tuple[str, ...]] = {}
        eligible: list[tuple[float, ModelCandidate]] = []
        considered: list[str] = []

        for candidate in candidates:
            considered.append(candidate.model_id)
            reasons = self._rejection_reasons(request, candidate)
            if reasons:
                rejected[candidate.model_id] = tuple(reasons)
                continue

            score = self._score(request, candidate)
            eligible.append((score, candidate))

        if not eligible:
            raise NoEligibleModelError(
                f"No eligible model for task {request.task_id!r}; rejected={rejected}"
            )

        eligible.sort(key=lambda item: (-item[0], item[1].model_id))
        best_score, best = eligible[0]
        return ModelSelectionEvidence(
            selected_model_id=best.model_id,
            score=round(best_score, 6),
            considered_models=tuple(considered),
            rejected=rejected,
        )

    def _rejection_reasons(
        self,
        request: IntelligenceRequest,
        candidate: ModelCandidate,
    ) -> list[str]:
        reasons: list[str] = []
        if not candidate.healthy:
            reasons.append("unhealthy")
        if request.privacy_required and not candidate.local:
            reasons.append("privacy_requires_local")
        if not request.modalities.issubset(candidate.modalities):
            reasons.append("missing_modality")
        if not request.required_capabilities.issubset(candidate.capabilities):
            reasons.append("missing_capability")
        if (
            request.max_latency_ms is not None
            and candidate.estimated_latency_ms > request.max_latency_ms
        ):
            reasons.append("latency_budget_exceeded")
        if (
            request.max_cost_units is not None
            and candidate.estimated_cost_units > request.max_cost_units
        ):
            reasons.append("cost_budget_exceeded")
        return reasons

    def _score(self, request: IntelligenceRequest, candidate: ModelCandidate) -> float:
        difficulty = self._DIFFICULTY_WEIGHT[request.difficulty]
        quality = candidate.benchmark_score
        latency_penalty = min(candidate.estimated_latency_ms / 120_000.0, 1.0)
        cost_penalty = min(candidate.estimated_cost_units / 100.0, 1.0)
        locality_bonus = 0.05 if candidate.local else 0.0
        return (
            quality * (0.65 + 0.25 * difficulty)
            + locality_bonus
            - 0.07 * latency_penalty
            - 0.03 * cost_penalty
        )


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_id: str
    domain: str
    success: bool
    score: float
    latency_ms: int
    retries: int = 0
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if not self.domain.strip():
            raise ValueError("domain must not be empty")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.retries < 0:
            raise ValueError("retries must be non-negative")


@dataclass(frozen=True)
class BenchmarkSummary:
    total_cases: int
    successful_cases: int
    success_rate: float
    mean_score: float
    mean_latency_ms: float
    by_domain: Mapping[str, float]


def summarize_benchmarks(results: Sequence[BenchmarkCaseResult]) -> BenchmarkSummary:
    if not results:
        return BenchmarkSummary(0, 0, 0.0, 0.0, 0.0, {})

    totals: dict[str, list[float]] = {}
    for result in results:
        totals.setdefault(result.domain, []).append(result.score)

    return BenchmarkSummary(
        total_cases=len(results),
        successful_cases=sum(1 for result in results if result.success),
        success_rate=round(sum(1 for result in results if result.success) / len(results), 6),
        mean_score=round(sum(result.score for result in results) / len(results), 6),
        mean_latency_ms=round(sum(result.latency_ms for result in results) / len(results), 3),
        by_domain={
            domain: round(sum(scores) / len(scores), 6)
            for domain, scores in sorted(totals.items())
        },
    )
