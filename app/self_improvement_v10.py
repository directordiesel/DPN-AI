from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from app.autonomous_coding_runtime_v10 import CodingMission, CodingMissionError
from app.benchmark_laboratory_v10 import BenchmarkLaboratory, BenchmarkRun, BenchmarkSummary


class SelfImprovementError(ValueError):
    """Raised when a self-improvement candidate violates the governed v10 contract."""


@dataclass(frozen=True)
class SelfImprovementPolicy:
    minimum_success_rate: float = 1.0
    minimum_quality_score: float = 1.0
    minimum_samples: int = 1
    max_success_regression: float = 0.0
    max_quality_regression: float = 0.0
    max_latency_regression_ratio: float = 0.25

    def validate(self) -> None:
        for name, value in (
            ("minimum_success_rate", self.minimum_success_rate),
            ("minimum_quality_score", self.minimum_quality_score),
            ("max_success_regression", self.max_success_regression),
            ("max_quality_regression", self.max_quality_regression),
            ("max_latency_regression_ratio", self.max_latency_regression_ratio),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise SelfImprovementError(f"{name} must be a finite number")
        if not 0.0 <= self.minimum_success_rate <= 1.0:
            raise SelfImprovementError("minimum_success_rate must be between 0 and 1")
        if not 0.0 <= self.minimum_quality_score <= 1.0:
            raise SelfImprovementError("minimum_quality_score must be between 0 and 1")
        if not 0.0 <= self.max_success_regression <= 1.0:
            raise SelfImprovementError("max_success_regression must be between 0 and 1")
        if not 0.0 <= self.max_quality_regression <= 1.0:
            raise SelfImprovementError("max_quality_regression must be between 0 and 1")
        if not 0.0 <= self.max_latency_regression_ratio <= 10.0:
            raise SelfImprovementError("max_latency_regression_ratio must be between 0 and 10")
        if isinstance(self.minimum_samples, bool) or not isinstance(self.minimum_samples, int) or self.minimum_samples < 1:
            raise SelfImprovementError("minimum_samples must be a positive integer")


@dataclass(frozen=True)
class ImprovementFamilyEvidence:
    task_family: str
    baseline_samples: int
    candidate_samples: int
    baseline_success_rate: float
    candidate_success_rate: float
    success_delta: float
    baseline_quality_score: float
    candidate_quality_score: float
    quality_delta: float
    baseline_median_latency_ms: int
    candidate_median_latency_ms: int
    latency_ratio: float
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class SelfImprovementEvaluation:
    schema_version: int
    candidate_id: str
    candidate_digest: str
    benchmark_model_name: str
    mission_id: str
    repository: str
    objective: str
    required_families: tuple[str, ...]
    families: tuple[ImprovementFamilyEvidence, ...]
    gate_passed: bool
    reason: str
    approval_required: bool = True
    execution_authorized: bool = False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["required_families"] = list(self.required_families)
        payload["families"] = [asdict(item) | {"failures": list(item.failures)} for item in self.families]
        return payload


@dataclass(frozen=True)
class ImprovementPromotionRequest:
    schema_version: int
    candidate_id: str
    candidate_digest: str
    mission_id: str
    repository: str
    approval_required: bool
    execution_authorized: bool
    required_authority: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class SelfImprovementEvidenceStore:
    """Atomic durable store for immutable self-improvement evaluation receipts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "evaluations": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SelfImprovementError("self-improvement evidence store is unreadable or corrupt") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("evaluations"), dict):
            raise SelfImprovementError("self-improvement evidence store schema is invalid")
        return payload

    def record(self, evaluation: SelfImprovementEvaluation) -> dict:
        payload = self._load()
        key = evaluation.candidate_digest
        record = evaluation.to_dict()
        existing = payload["evaluations"].get(key)
        if existing is not None:
            if existing != record:
                raise SelfImprovementError("candidate digest already exists with different evidence")
            return existing
        payload["evaluations"][key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return record

    def get(self, candidate_digest: str) -> dict | None:
        return self._load()["evaluations"].get(candidate_digest)


class BenchmarkGatedSelfImprovement:
    """Evidence-only self-improvement gate for DPN AI v10.

    This controller cannot edit repositories, execute tools, approve requests, merge
    code, or activate capabilities. It evaluates trusted benchmark runs supplied by
    the host, requires an already-READY autonomous coding mission, persists an
    immutable receipt, and may only emit a non-executable human-approval request.
    """

    def __init__(self, evidence_store: SelfImprovementEvidenceStore, *, policy: SelfImprovementPolicy | None = None) -> None:
        self.evidence_store = evidence_store
        self.policy = policy or SelfImprovementPolicy()
        self.policy.validate()

    @staticmethod
    def _summaries_for_model(runs: Iterable[BenchmarkRun], model_name: str) -> Mapping[str, BenchmarkSummary]:
        summaries = BenchmarkLaboratory.summarize(run for run in runs if run.model_name == model_name)
        result: dict[str, BenchmarkSummary] = {}
        for summary in summaries:
            if summary.task_family in result:
                raise SelfImprovementError("benchmark evidence contains duplicate family summaries")
            result[summary.task_family] = summary
        return result

    @staticmethod
    def _candidate_digest(
        *,
        candidate_id: str,
        mission: CodingMission,
        benchmark_model_name: str,
        required_families: tuple[str, ...],
        family_evidence: tuple[ImprovementFamilyEvidence, ...],
    ) -> str:
        payload = {
            "candidate_id": candidate_id,
            "mission_id": mission.mission_id,
            "repository": mission.repository,
            "objective": mission.objective,
            "affected_files": sorted(mission.affected_files),
            "affected_tests": sorted(mission.affected_tests),
            "benchmark_model_name": benchmark_model_name,
            "required_families": list(required_families),
            "families": [asdict(item) for item in family_evidence],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def evaluate(
        self,
        *,
        candidate_id: str,
        mission: CodingMission,
        benchmark_model_name: str,
        required_task_families: Iterable[str],
        baseline_runs: Iterable[BenchmarkRun],
        candidate_runs: Iterable[BenchmarkRun],
    ) -> SelfImprovementEvaluation:
        candidate_id = candidate_id.strip()
        benchmark_model_name = benchmark_model_name.strip()
        if not candidate_id:
            raise SelfImprovementError("candidate_id is required")
        if not benchmark_model_name:
            raise SelfImprovementError("benchmark_model_name is required")
        try:
            mission.require_ready()
        except CodingMissionError as exc:
            raise SelfImprovementError("self-improvement candidate requires a fully READY coding mission") from exc

        required = tuple(sorted({item.strip() for item in required_task_families if item and item.strip()}))
        if not required:
            raise SelfImprovementError("at least one required benchmark family is required")

        baseline = self._summaries_for_model(tuple(baseline_runs), benchmark_model_name)
        candidate = self._summaries_for_model(tuple(candidate_runs), benchmark_model_name)
        evidence: list[ImprovementFamilyEvidence] = []

        for family in required:
            before = baseline.get(family)
            after = candidate.get(family)
            if before is None or after is None:
                raise SelfImprovementError(f"missing baseline or candidate benchmark evidence for {family}")
            failures: list[str] = []
            if before.samples < self.policy.minimum_samples or after.samples < self.policy.minimum_samples:
                failures.append("samples")
            if after.success_rate < self.policy.minimum_success_rate:
                failures.append("minimum_success_rate")
            if after.mean_quality_score < self.policy.minimum_quality_score:
                failures.append("minimum_quality_score")
            success_delta = after.success_rate - before.success_rate
            quality_delta = after.mean_quality_score - before.mean_quality_score
            if success_delta < -self.policy.max_success_regression:
                failures.append("success_regression")
            if quality_delta < -self.policy.max_quality_regression:
                failures.append("quality_regression")
            if before.median_latency_ms == 0:
                latency_ratio = 1.0 if after.median_latency_ms == 0 else 1.0 + self.policy.max_latency_regression_ratio + 1.0
            else:
                latency_ratio = after.median_latency_ms / before.median_latency_ms
            if latency_ratio > 1.0 + self.policy.max_latency_regression_ratio:
                failures.append("latency_regression")
            evidence.append(
                ImprovementFamilyEvidence(
                    task_family=family,
                    baseline_samples=before.samples,
                    candidate_samples=after.samples,
                    baseline_success_rate=before.success_rate,
                    candidate_success_rate=after.success_rate,
                    success_delta=success_delta,
                    baseline_quality_score=before.mean_quality_score,
                    candidate_quality_score=after.mean_quality_score,
                    quality_delta=quality_delta,
                    baseline_median_latency_ms=before.median_latency_ms,
                    candidate_median_latency_ms=after.median_latency_ms,
                    latency_ratio=latency_ratio,
                    passed=not failures,
                    failures=tuple(failures),
                )
            )

        family_evidence = tuple(evidence)
        gate_passed = all(item.passed for item in family_evidence)
        digest = self._candidate_digest(
            candidate_id=candidate_id,
            mission=mission,
            benchmark_model_name=benchmark_model_name,
            required_families=required,
            family_evidence=family_evidence,
        )
        evaluation = SelfImprovementEvaluation(
            schema_version=1,
            candidate_id=candidate_id,
            candidate_digest=digest,
            benchmark_model_name=benchmark_model_name,
            mission_id=mission.mission_id,
            repository=mission.repository,
            objective=mission.objective,
            required_families=required,
            families=family_evidence,
            gate_passed=gate_passed,
            reason="benchmark gate passed; explicit human approval is still required" if gate_passed else "benchmark gate failed closed",
        )
        self.evidence_store.record(evaluation)
        return evaluation

    def request_promotion(self, evaluation: SelfImprovementEvaluation) -> ImprovementPromotionRequest:
        if not evaluation.gate_passed:
            raise SelfImprovementError("failed benchmark evidence cannot request promotion")
        stored = self.evidence_store.get(evaluation.candidate_digest)
        if stored != evaluation.to_dict():
            raise SelfImprovementError("promotion requires exact durable evaluation evidence")
        return ImprovementPromotionRequest(
            schema_version=1,
            candidate_id=evaluation.candidate_id,
            candidate_digest=evaluation.candidate_digest,
            mission_id=evaluation.mission_id,
            repository=evaluation.repository,
            approval_required=True,
            execution_authorized=False,
            required_authority="explicit_human_approval",
            reason="candidate passed benchmark/review/security/CI gates; application remains separately approval-controlled",
        )


__all__ = [
    "BenchmarkGatedSelfImprovement",
    "ImprovementFamilyEvidence",
    "ImprovementPromotionRequest",
    "SelfImprovementError",
    "SelfImprovementEvaluation",
    "SelfImprovementEvidenceStore",
    "SelfImprovementPolicy",
]
