from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkSummary


class BenchmarkReadinessError(ValueError):
    """Raised when benchmark evidence cannot satisfy a v10 readiness gate."""


@dataclass(frozen=True)
class LeaderboardEntry:
    rank: int
    model_name: str
    task_family: str
    success_rate: float
    quality_score: float
    median_latency_ms: int | None
    sample_count: int
    score: float


@dataclass(frozen=True)
class ReadinessGateResult:
    ready: bool
    reason: str
    evaluated_profiles: int
    passing_profiles: int
    failing_profiles: tuple[str, ...]


def _leaderboard_score(summary: BenchmarkSummary) -> float:
    latency_penalty = 0.0 if summary.median_latency_ms is None else min(0.20, summary.median_latency_ms / 100_000.0)
    evidence_strength = min(1.0, summary.sample_count / 100.0)
    return (
        summary.success_rate * 0.60
        + summary.quality_score * 0.25
        + evidence_strength * 0.15
        - latency_penalty
    )


def build_leaderboard(summaries: Iterable[BenchmarkSummary]) -> tuple[LeaderboardEntry, ...]:
    materialized = list(summaries)
    if not materialized:
        return ()

    ordered = sorted(
        materialized,
        key=lambda item: (
            -_leaderboard_score(item),
            -item.success_rate,
            -item.quality_score,
            item.median_latency_ms if item.median_latency_ms is not None else 1_000_000_000,
            item.model_name.lower(),
            item.task_family.lower(),
        ),
    )
    return tuple(
        LeaderboardEntry(
            rank=index + 1,
            model_name=summary.model_name,
            task_family=summary.task_family,
            success_rate=summary.success_rate,
            quality_score=summary.quality_score,
            median_latency_ms=summary.median_latency_ms,
            sample_count=summary.sample_count,
            score=_leaderboard_score(summary),
        )
        for index, summary in enumerate(ordered)
    )


def evaluate_readiness(
    summaries: Iterable[BenchmarkSummary],
    *,
    required_task_families: Iterable[str],
    minimum_success_rate: float = 0.80,
    minimum_quality_score: float = 0.70,
    minimum_samples: int = 20,
) -> ReadinessGateResult:
    if not 0.0 <= minimum_success_rate <= 1.0:
        raise BenchmarkReadinessError("minimum success rate must be between 0 and 1")
    if not 0.0 <= minimum_quality_score <= 1.0:
        raise BenchmarkReadinessError("minimum quality score must be between 0 and 1")
    if minimum_samples < 1:
        raise BenchmarkReadinessError("minimum samples must be positive")

    required = tuple(sorted({item.strip() for item in required_task_families if item.strip()}))
    if not required:
        raise BenchmarkReadinessError("at least one required task family is required")

    materialized = list(summaries)
    if not materialized:
        return ReadinessGateResult(False, "no benchmark evidence is available", 0, 0, required)

    best_by_family: dict[str, BenchmarkSummary] = {}
    for summary in materialized:
        if summary.task_family not in required:
            continue
        current = best_by_family.get(summary.task_family)
        if current is None or _leaderboard_score(summary) > _leaderboard_score(current):
            best_by_family[summary.task_family] = summary

    failures: list[str] = []
    passing = 0
    for family in required:
        summary = best_by_family.get(family)
        if summary is None:
            failures.append(f"{family}:missing")
            continue
        family_failures: list[str] = []
        if summary.sample_count < minimum_samples:
            family_failures.append("samples")
        if summary.success_rate < minimum_success_rate:
            family_failures.append("success_rate")
        if summary.quality_score < minimum_quality_score:
            family_failures.append("quality_score")
        if family_failures:
            failures.append(f"{family}:{','.join(family_failures)}")
        else:
            passing += 1

    ready = not failures
    reason = "benchmark readiness gate passed" if ready else "benchmark readiness gate failed closed"
    return ReadinessGateResult(
        ready=ready,
        reason=reason,
        evaluated_profiles=len(required),
        passing_profiles=passing,
        failing_profiles=tuple(failures),
    )


__all__ = [
    "BenchmarkReadinessError",
    "LeaderboardEntry",
    "ReadinessGateResult",
    "build_leaderboard",
    "evaluate_readiness",
]
