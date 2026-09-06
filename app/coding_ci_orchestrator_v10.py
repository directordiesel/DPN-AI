from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.autonomous_coding_runtime_v10 import CodingMission, CodingMissionError, CodingStage
from app.coding_repair_engine_v10 import (
    CodingRepairEngine,
    FailureDiagnosis,
    FailureKind,
    RepairDecision,
    RepairDisposition,
    ValidationResult,
)
from app.coding_repository_intelligence_v10 import DiffRisk, PullRequestEvidence


class CIJobConclusion(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class CIJobEvidence:
    name: str
    conclusion: CIJobConclusion
    failed_step: str = ""
    log_excerpt: str = ""
    affected_paths: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.name.strip():
            raise CodingMissionError("CI job name is required")
        if any(not path.strip() for path in self.affected_paths):
            raise CodingMissionError("CI affected paths must be non-empty")

    @property
    def passed(self) -> bool:
        return self.conclusion in {CIJobConclusion.SUCCESS, CIJobConclusion.SKIPPED, CIJobConclusion.NEUTRAL}


@dataclass(frozen=True)
class CIAnalysis:
    passed: bool
    jobs_evaluated: int
    failed_jobs: tuple[str, ...]
    diagnosis: FailureDiagnosis | None


@dataclass(frozen=True)
class CodingOrchestrationResult:
    next_stage: CodingStage
    ci: CIAnalysis
    repair: RepairDecision | None
    pr_ready: bool
    reason: str


class CodingCIOrchestrator:
    """Bridge GitHub-style CI evidence into the v10 coding repair loop.

    The orchestrator consumes recorded job evidence only. It never invents CI
    success, never marks a mission ready from partial status, and preserves the
    repair budget and diff-risk approval rules enforced by CodingRepairEngine.
    """

    @staticmethod
    def analyze_jobs(jobs: Iterable[CIJobEvidence]) -> CIAnalysis:
        materialized = list(jobs)
        if not materialized:
            raise CodingMissionError("at least one CI job result is required")
        for job in materialized:
            job.validate()

        failed = [job for job in materialized if not job.passed]
        if not failed:
            return CIAnalysis(True, len(materialized), (), None)

        validation_results = []
        affected: list[str] = []
        for job in failed:
            detail = "\n".join(part for part in (job.failed_step, job.log_excerpt) if part)
            validation_results.append(ValidationResult(name=f"ci:{job.name}", passed=False, output=detail))
            affected.extend(job.affected_paths)

        diagnosis = CodingRepairEngine.diagnose(validation_results)
        if diagnosis.kind == FailureKind.UNKNOWN:
            diagnosis = FailureDiagnosis(
                FailureKind.CI,
                f"{len(failed)} CI job(s) failed without a more specific classifier",
                True,
                affected_paths=tuple(dict.fromkeys(affected)),
                evidence=tuple(job.name for job in failed),
            )
        else:
            diagnosis = FailureDiagnosis(
                diagnosis.kind,
                diagnosis.summary,
                diagnosis.repairable,
                affected_paths=tuple(dict.fromkeys(affected)),
                evidence=diagnosis.evidence,
            )

        return CIAnalysis(
            False,
            len(materialized),
            tuple(job.name for job in failed),
            diagnosis,
        )

    @classmethod
    def route(
        cls,
        mission: CodingMission,
        jobs: Iterable[CIJobEvidence],
        *,
        diff_risk: DiffRisk,
        approval_granted: bool = False,
        pr_evidence: PullRequestEvidence | None = None,
    ) -> CodingOrchestrationResult:
        mission.validate()
        ci = cls.analyze_jobs(jobs)

        if ci.passed:
            mission.mark_ci(True)
            if pr_evidence is not None and pr_evidence.ready and mission.review_passed and mission.security_passed:
                next_stage = CodingStage.READY
                reason = "CI and PR-readiness evidence are complete"
                return CodingOrchestrationResult(next_stage, ci, None, True, reason)
            return CodingOrchestrationResult(
                CodingStage.READY if mission.review_passed and mission.security_passed else CodingStage.REVIEW,
                ci,
                None,
                False,
                "CI passed; review/security/PR evidence must still be satisfied",
            )

        mission.mark_ci(False)
        if ci.diagnosis is None:
            raise CodingMissionError("failed CI analysis must include a diagnosis")

        decision = CodingRepairEngine.decide_repair(
            mission,
            ci.diagnosis,
            diff_risk=diff_risk,
            approval_granted=approval_granted,
        )

        if decision.disposition == RepairDisposition.REPAIR:
            mission.record_repair()
            next_stage = CodingStage.REPAIR
        else:
            next_stage = CodingStage.FAILED

        return CodingOrchestrationResult(
            next_stage=next_stage,
            ci=ci,
            repair=decision,
            pr_ready=False,
            reason=decision.reason,
        )


__all__ = [
    "CIAnalysis",
    "CIJobConclusion",
    "CIJobEvidence",
    "CodingCIOrchestrator",
    "CodingOrchestrationResult",
]
