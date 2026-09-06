from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Iterable

from app.model_intelligence_v10 import BenchmarkProfile
from app.model_routing_v9 import ModelRoutingError


@dataclass(frozen=True)
class BenchmarkRun:
    model_name: str
    task_family: str
    task_id: str
    passed: bool
    quality_score: float
    latency_ms: int
    retries: int = 0
    token_usage: int | None = None
    created_at: str = ""

    def validate(self) -> None:
        if not self.model_name.strip():
            raise ModelRoutingError("benchmark run model name is required")
        if not self.task_family.strip():
            raise ModelRoutingError("benchmark run task family is required")
        if not self.task_id.strip():
            raise ModelRoutingError("benchmark run task id is required")
        if isinstance(self.quality_score, bool) or not isinstance(self.quality_score, (int, float)):
            raise ModelRoutingError("benchmark run quality score must be numeric")
        if not math.isfinite(float(self.quality_score)) or not 0.0 <= float(self.quality_score) <= 1.0:
            raise ModelRoutingError("benchmark run quality score must be between 0 and 1")
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int) or self.latency_ms < 0:
            raise ModelRoutingError("benchmark run latency must be a non-negative integer")
        if isinstance(self.retries, bool) or not isinstance(self.retries, int) or self.retries < 0:
            raise ModelRoutingError("benchmark run retries must be a non-negative integer")
        if self.token_usage is not None and (
            isinstance(self.token_usage, bool) or not isinstance(self.token_usage, int) or self.token_usage < 0
        ):
            raise ModelRoutingError("benchmark run token usage must be a non-negative integer")

    def normalized(self) -> "BenchmarkRun":
        self.validate()
        return BenchmarkRun(
            model_name=self.model_name.strip(),
            task_family=self.task_family.strip(),
            task_id=self.task_id.strip(),
            passed=bool(self.passed),
            quality_score=float(self.quality_score),
            latency_ms=self.latency_ms,
            retries=self.retries,
            token_usage=self.token_usage,
            created_at=self.created_at or datetime.now(timezone.utc).isoformat(),
        )


@dataclass(frozen=True)
class BenchmarkSummary:
    model_name: str
    task_family: str
    samples: int
    passed: int
    success_rate: float
    mean_quality_score: float
    median_latency_ms: int
    total_retries: int
    total_token_usage: int | None

    def to_profile(self) -> BenchmarkProfile:
        return BenchmarkProfile(
            model_name=self.model_name,
            task_family=self.task_family,
            success_rate=self.success_rate,
            sample_count=self.samples,
            median_latency_ms=self.median_latency_ms,
            quality_score=self.mean_quality_score,
        )


@dataclass(frozen=True)
class RegressionSignal:
    model_name: str
    task_family: str
    baseline_success_rate: float
    current_success_rate: float
    delta: float
    regressed: bool


class BenchmarkLaboratory:
    """Persistent benchmark evidence store for DPN AI v10.

    JSONL keeps each benchmark run append-only and auditable. The laboratory does
    not fabricate results; summaries and regressions are derived only from recorded
    runs supplied by an evaluator or test harness.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, run: BenchmarkRun) -> BenchmarkRun:
        normalized = run.normalized()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(normalized), sort_keys=True) + "\n")
        return normalized

    def load(self) -> list[BenchmarkRun]:
        if not self.path.exists():
            return []
        runs: list[BenchmarkRun] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    run = BenchmarkRun(**payload).normalized()
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ModelRoutingError(f"invalid benchmark record at line {line_number}") from exc
                runs.append(run)
        return runs

    @staticmethod
    def summarize(runs: Iterable[BenchmarkRun]) -> list[BenchmarkSummary]:
        groups: dict[tuple[str, str], list[BenchmarkRun]] = {}
        for run in runs:
            normalized = run.normalized()
            groups.setdefault((normalized.model_name, normalized.task_family), []).append(normalized)

        summaries: list[BenchmarkSummary] = []
        for (model_name, task_family), group in sorted(groups.items()):
            samples = len(group)
            passed = sum(1 for item in group if item.passed)
            success_rate = passed / samples
            quality = sum(item.quality_score for item in group) / samples
            latency = int(median(item.latency_ms for item in group))
            retries = sum(item.retries for item in group)
            token_values = [item.token_usage for item in group if item.token_usage is not None]
            summaries.append(
                BenchmarkSummary(
                    model_name=model_name,
                    task_family=task_family,
                    samples=samples,
                    passed=passed,
                    success_rate=success_rate,
                    mean_quality_score=quality,
                    median_latency_ms=latency,
                    total_retries=retries,
                    total_token_usage=sum(token_values) if token_values else None,
                )
            )
        return summaries

    def profiles(self) -> list[BenchmarkProfile]:
        return [summary.to_profile() for summary in self.summarize(self.load())]

    @staticmethod
    def regressions(
        baseline: Iterable[BenchmarkSummary],
        current: Iterable[BenchmarkSummary],
        *,
        threshold: float = 0.05,
    ) -> list[RegressionSignal]:
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ModelRoutingError("regression threshold must be numeric")
        if not math.isfinite(float(threshold)) or not 0.0 <= float(threshold) <= 1.0:
            raise ModelRoutingError("regression threshold must be between 0 and 1")

        baseline_map = {(item.model_name, item.task_family): item for item in baseline}
        signals: list[RegressionSignal] = []
        for item in current:
            previous = baseline_map.get((item.model_name, item.task_family))
            if previous is None:
                continue
            delta = item.success_rate - previous.success_rate
            signals.append(
                RegressionSignal(
                    model_name=item.model_name,
                    task_family=item.task_family,
                    baseline_success_rate=previous.success_rate,
                    current_success_rate=item.success_rate,
                    delta=delta,
                    regressed=delta <= -float(threshold),
                )
            )
        return signals


__all__ = [
    "BenchmarkLaboratory",
    "BenchmarkRun",
    "BenchmarkSummary",
    "RegressionSignal",
]
