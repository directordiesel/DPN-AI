from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import median
from typing import Iterable

from app.benchmark_laboratory_v10 import BenchmarkRun
from app.model_routing_v9 import ModelRoutingError


class PerformanceOptimizationError(ValueError):
    """Raised when Batch 17 optimization evidence is incomplete or unsafe."""


@dataclass(frozen=True)
class PerformanceOptimizationPolicy:
    minimum_success_rate: float = 1.0
    minimum_quality_score: float = 1.0
    minimum_samples_per_family: int = 1
    max_success_regression: float = 0.0
    max_quality_regression: float = 0.0
    max_latency_regression_ratio: float = 0.0
    max_token_regression_ratio: float = 0.0
    max_retry_regression: int = 0
    require_measurable_improvement: bool = True

    def validate(self) -> None:
        numeric = (
            ("minimum_success_rate", self.minimum_success_rate),
            ("minimum_quality_score", self.minimum_quality_score),
            ("max_success_regression", self.max_success_regression),
            ("max_quality_regression", self.max_quality_regression),
            ("max_latency_regression_ratio", self.max_latency_regression_ratio),
            ("max_token_regression_ratio", self.max_token_regression_ratio),
        )
        for name, value in numeric:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise PerformanceOptimizationError(f"{name} must be a finite number")
        if not 0.0 <= float(self.minimum_success_rate) <= 1.0:
            raise PerformanceOptimizationError("minimum_success_rate must be between 0 and 1")
        if not 0.0 <= float(self.minimum_quality_score) <= 1.0:
            raise PerformanceOptimizationError("minimum_quality_score must be between 0 and 1")
        if not 0.0 <= float(self.max_success_regression) <= 1.0:
            raise PerformanceOptimizationError("max_success_regression must be between 0 and 1")
        if not 0.0 <= float(self.max_quality_regression) <= 1.0:
            raise PerformanceOptimizationError("max_quality_regression must be between 0 and 1")
        if not 0.0 <= float(self.max_latency_regression_ratio) <= 10.0:
            raise PerformanceOptimizationError("max_latency_regression_ratio must be between 0 and 10")
        if not 0.0 <= float(self.max_token_regression_ratio) <= 10.0:
            raise PerformanceOptimizationError("max_token_regression_ratio must be between 0 and 10")
        if (
            isinstance(self.minimum_samples_per_family, bool)
            or not isinstance(self.minimum_samples_per_family, int)
            or self.minimum_samples_per_family < 1
        ):
            raise PerformanceOptimizationError("minimum_samples_per_family must be a positive integer")
        if isinstance(self.max_retry_regression, bool) or not isinstance(self.max_retry_regression, int) or self.max_retry_regression < 0:
            raise PerformanceOptimizationError("max_retry_regression must be a non-negative integer")
        if not isinstance(self.require_measurable_improvement, bool):
            raise PerformanceOptimizationError("require_measurable_improvement must be a boolean")


@dataclass(frozen=True)
class PerformanceFamilyEvidence:
    task_family: str
    task_ids: tuple[str, ...]
    samples: int
    baseline_success_rate: float
    candidate_success_rate: float
    success_delta: float
    baseline_quality_score: float
    candidate_quality_score: float
    quality_delta: float
    baseline_median_latency_ms: int
    candidate_median_latency_ms: int
    latency_ratio: float
    baseline_total_retries: int
    candidate_total_retries: int
    retry_delta: int
    baseline_total_tokens: int | None
    candidate_total_tokens: int | None
    token_ratio: float | None
    measurable_improvement: bool
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class PerformanceOptimizationEvaluation:
    schema_version: int
    candidate_id: str
    candidate_digest: str
    model_name: str
    required_families: tuple[str, ...]
    families: tuple[PerformanceFamilyEvidence, ...]
    gate_passed: bool
    measurable_improvement: bool
    reason: str
    execution_authorized: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["required_families"] = list(self.required_families)
        payload["families"] = [asdict(item) | {"task_ids": list(item.task_ids), "failures": list(item.failures)} for item in self.families]
        return payload


class PerformanceOptimizationEvaluator:
    """Fail-closed Batch 17 baseline/candidate performance authority.

    The evaluator consumes benchmark evidence only. It does not execute benchmarks,
    modify routing, apply code, or authorize deployment. Exact task-set parity is
    mandatory so a candidate cannot appear faster by omitting difficult cases.
    """

    def __init__(self, *, policy: PerformanceOptimizationPolicy | None = None) -> None:
        self.policy = policy or PerformanceOptimizationPolicy()
        self.policy.validate()

    @staticmethod
    def _normalize_runs(runs: Iterable[BenchmarkRun], *, model_name: str) -> tuple[BenchmarkRun, ...]:
        normalized: list[BenchmarkRun] = []
        for run in runs:
            try:
                item = run.normalized()
            except (ModelRoutingError, AttributeError) as exc:
                raise PerformanceOptimizationError("invalid benchmark evidence") from exc
            if item.model_name == model_name:
                normalized.append(item)
        return tuple(normalized)

    @staticmethod
    def _family_runs(runs: tuple[BenchmarkRun, ...], family: str) -> tuple[BenchmarkRun, ...]:
        selected = tuple(item for item in runs if item.task_family == family)
        ids = [item.task_id for item in selected]
        if len(ids) != len(set(ids)):
            raise PerformanceOptimizationError(f"duplicate benchmark task_id evidence for {family}")
        return selected

    @staticmethod
    def _safe_ratio(candidate: int, baseline: int) -> float:
        if baseline == 0:
            return 1.0 if candidate == 0 else float(candidate + 1)
        return candidate / baseline

    @staticmethod
    def _token_total(runs: tuple[BenchmarkRun, ...]) -> int | None:
        values = [item.token_usage for item in runs]
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise PerformanceOptimizationError("token evidence must be complete for every task or absent for every task")
        return sum(int(value) for value in values if value is not None)

    def evaluate(
        self,
        *,
        candidate_id: str,
        model_name: str,
        required_task_families: Iterable[str],
        baseline_runs: Iterable[BenchmarkRun],
        candidate_runs: Iterable[BenchmarkRun],
    ) -> PerformanceOptimizationEvaluation:
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise PerformanceOptimizationError("candidate_id is required")
        if not isinstance(model_name, str) or not model_name.strip():
            raise PerformanceOptimizationError("model_name is required")
        candidate_id = candidate_id.strip()
        model_name = model_name.strip()

        try:
            family_items = tuple(required_task_families)
        except TypeError as exc:
            raise PerformanceOptimizationError("required_task_families must be iterable") from exc
        if any(not isinstance(item, str) for item in family_items):
            raise PerformanceOptimizationError("required benchmark family identifiers must be strings")
        required = tuple(sorted({item.strip() for item in family_items if item.strip()}))
        if not required:
            raise PerformanceOptimizationError("at least one required benchmark family is required")

        try:
            baseline_items = tuple(baseline_runs)
            candidate_items = tuple(candidate_runs)
        except TypeError as exc:
            raise PerformanceOptimizationError("benchmark evidence must be iterable") from exc
        baseline = self._normalize_runs(baseline_items, model_name=model_name)
        candidate = self._normalize_runs(candidate_items, model_name=model_name)
        family_evidence: list[PerformanceFamilyEvidence] = []

        for family in required:
            before = self._family_runs(baseline, family)
            after = self._family_runs(candidate, family)
            if not before or not after:
                raise PerformanceOptimizationError(f"missing baseline or candidate evidence for {family}")

            before_ids = tuple(sorted(item.task_id for item in before))
            after_ids = tuple(sorted(item.task_id for item in after))
            if before_ids != after_ids:
                raise PerformanceOptimizationError(f"baseline/candidate task-set mismatch for {family}")
            if len(before) < self.policy.minimum_samples_per_family:
                raise PerformanceOptimizationError(f"insufficient benchmark samples for {family}")

            before_by_id = {item.task_id: item for item in before}
            after_by_id = {item.task_id: item for item in after}
            before_ordered = tuple(before_by_id[task_id] for task_id in before_ids)
            after_ordered = tuple(after_by_id[task_id] for task_id in before_ids)

            baseline_success = sum(1 for item in before_ordered if item.passed) / len(before_ordered)
            candidate_success = sum(1 for item in after_ordered if item.passed) / len(after_ordered)
            baseline_quality = sum(item.quality_score for item in before_ordered) / len(before_ordered)
            candidate_quality = sum(item.quality_score for item in after_ordered) / len(after_ordered)
            baseline_latency = int(median(item.latency_ms for item in before_ordered))
            candidate_latency = int(median(item.latency_ms for item in after_ordered))
            baseline_retries = sum(item.retries for item in before_ordered)
            candidate_retries = sum(item.retries for item in after_ordered)
            baseline_tokens = self._token_total(before_ordered)
            candidate_tokens = self._token_total(after_ordered)

            if (baseline_tokens is None) != (candidate_tokens is None):
                raise PerformanceOptimizationError(f"baseline/candidate token evidence availability mismatch for {family}")

            success_delta = candidate_success - baseline_success
            quality_delta = candidate_quality - baseline_quality
            latency_ratio = self._safe_ratio(candidate_latency, baseline_latency)
            retry_delta = candidate_retries - baseline_retries
            token_ratio = None
            if baseline_tokens is not None and candidate_tokens is not None:
                token_ratio = self._safe_ratio(candidate_tokens, baseline_tokens)

            failures: list[str] = []
            if candidate_success < self.policy.minimum_success_rate:
                failures.append("minimum_success_rate")
            if candidate_quality < self.policy.minimum_quality_score:
                failures.append("minimum_quality_score")
            if success_delta < -self.policy.max_success_regression:
                failures.append("success_regression")
            if quality_delta < -self.policy.max_quality_regression:
                failures.append("quality_regression")
            if latency_ratio > 1.0 + self.policy.max_latency_regression_ratio:
                failures.append("latency_regression")
            if retry_delta > self.policy.max_retry_regression:
                failures.append("retry_regression")
            if token_ratio is not None and token_ratio > 1.0 + self.policy.max_token_regression_ratio:
                failures.append("token_regression")

            improved = (
                candidate_latency < baseline_latency
                or candidate_retries < baseline_retries
                or (
                    baseline_tokens is not None
                    and candidate_tokens is not None
                    and candidate_tokens < baseline_tokens
                )
            )
            family_evidence.append(
                PerformanceFamilyEvidence(
                    task_family=family,
                    task_ids=before_ids,
                    samples=len(before_ordered),
                    baseline_success_rate=baseline_success,
                    candidate_success_rate=candidate_success,
                    success_delta=success_delta,
                    baseline_quality_score=baseline_quality,
                    candidate_quality_score=candidate_quality,
                    quality_delta=quality_delta,
                    baseline_median_latency_ms=baseline_latency,
                    candidate_median_latency_ms=candidate_latency,
                    latency_ratio=latency_ratio,
                    baseline_total_retries=baseline_retries,
                    candidate_total_retries=candidate_retries,
                    retry_delta=retry_delta,
                    baseline_total_tokens=baseline_tokens,
                    candidate_total_tokens=candidate_tokens,
                    token_ratio=token_ratio,
                    measurable_improvement=improved,
                    passed=not failures,
                    failures=tuple(failures),
                )
            )

        families = tuple(family_evidence)
        measurable_improvement = any(item.measurable_improvement for item in families)
        gate_passed = all(item.passed for item in families)
        if self.policy.require_measurable_improvement and not measurable_improvement:
            gate_passed = False

        digest_payload = {
            "candidate_id": candidate_id,
            "model_name": model_name,
            "required_families": list(required),
            "families": [asdict(item) for item in families],
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        reason = (
            "performance gate passed with measurable improvement; execution remains unauthorized"
            if gate_passed
            else "performance gate failed closed"
        )
        return PerformanceOptimizationEvaluation(
            schema_version=1,
            candidate_id=candidate_id,
            candidate_digest=digest,
            model_name=model_name,
            required_families=required,
            families=families,
            gate_passed=gate_passed,
            measurable_improvement=measurable_improvement,
            reason=reason,
            execution_authorized=False,
        )


__all__ = [
    "PerformanceFamilyEvidence",
    "PerformanceOptimizationError",
    "PerformanceOptimizationEvaluation",
    "PerformanceOptimizationEvaluator",
    "PerformanceOptimizationPolicy",
]
