from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.autonomous_coding_runtime_v10 import AutonomousCodingRuntime, CodingMission, CodingMissionError, CodingStage
from app.coding_ci_orchestrator_v10 import CIJobEvidence, CodingCIOrchestrator, CodingOrchestrationResult
from app.coding_repair_engine_v10 import ChangePlanStep, CodingRepairEngine, RepairDisposition, ValidationResult
from app.coding_repository_intelligence_v10 import (
    ChangeImpact,
    DiffRiskAssessment,
    PullRequestEvidence,
    RepositoryIntelligence,
    RepositoryMap,
)


@dataclass(frozen=True)
class CodingCoordinatorSnapshot:
    stage: CodingStage
    impact: ChangeImpact
    risk: DiffRiskAssessment
    plan: tuple[ChangePlanStep, ...]
    validation_passed: bool
    pr_evidence: PullRequestEvidence | None
    ci_result: CodingOrchestrationResult | None
    ready: bool
    reason: str


class AutonomousCodingCoordinator:
    """End-to-end coordinator for DPN AI v10 autonomous coding missions.

    The coordinator composes repository intelligence, planning, validation,
    bounded repair policy, review/security evidence, and CI evidence. It does not
    perform repository writes or provider calls itself; those remain delegated to
    governed tools. Readiness is evidence-backed and fail-closed.
    """

    def __init__(self) -> None:
        self.runtime = AutonomousCodingRuntime()

    def prepare(
        self,
        mission: CodingMission,
        *,
        repository_map: RepositoryMap,
        changed_files: Iterable[str],
        plan_steps: Iterable[ChangePlanStep],
        added_lines: int = 0,
        deleted_lines: int = 0,
    ) -> CodingCoordinatorSnapshot:
        self.runtime.begin(mission)
        impact = RepositoryIntelligence.analyze_change_impact(repository_map, changed_files)
        if impact.missing_paths:
            raise CodingMissionError("change plan references paths missing from repository evidence")
        plan = CodingRepairEngine.build_change_plan(plan_steps)
        planned_paths = {step.path for step in plan if step.action != "inspect"}
        if planned_paths and not planned_paths.issubset(set(impact.changed_files)):
            raise CodingMissionError("change plan contains paths outside analyzed change impact")
        risk = RepositoryIntelligence.classify_diff_risk(
            impact.changed_files,
            added_lines=added_lines,
            deleted_lines=deleted_lines,
        )
        mission.affected_files = list(impact.changed_files)
        mission.affected_tests = list(impact.directly_affected_tests)
        mission.advance(CodingStage.PLAN)
        mission.advance(CodingStage.ISOLATE)
        mission.advance(CodingStage.EDIT)
        mission.advance(CodingStage.VALIDATE)
        return CodingCoordinatorSnapshot(
            stage=mission.stage,
            impact=impact,
            risk=risk,
            plan=plan,
            validation_passed=False,
            pr_evidence=None,
            ci_result=None,
            ready=False,
            reason="mission prepared for validation",
        )

    def validate_or_route_repair(
        self,
        mission: CodingMission,
        *,
        validation_results: Iterable[ValidationResult],
        risk: DiffRiskAssessment,
        approval_granted: bool = False,
    ) -> tuple[bool, str]:
        results = tuple(validation_results)
        all_passed = CodingRepairEngine.record_validation_results(mission, results)
        if all_passed:
            mission.advance(CodingStage.REVIEW)
            return True, "validation passed; mission advanced to review"

        mission.advance(CodingStage.DIAGNOSE)
        diagnosis = CodingRepairEngine.diagnose(results)
        decision = CodingRepairEngine.decide_repair(
            mission,
            diagnosis,
            diff_risk=risk.risk,
            approval_granted=approval_granted,
        )
        if decision.disposition == RepairDisposition.REPAIR:
            mission.advance(CodingStage.REPAIR)
            mission.record_repair()
            return False, decision.reason

        mission.fail(decision.reason)
        return False, decision.reason

    @staticmethod
    def record_review(mission: CodingMission, *, review_passed: bool, security_passed: bool) -> None:
        if mission.stage != CodingStage.REVIEW:
            raise CodingMissionError("review evidence can only be recorded during review stage")
        mission.mark_review(review_passed=review_passed, security_passed=security_passed)
        if review_passed and security_passed:
            mission.advance(CodingStage.CI)
        elif mission.repair_attempts < mission.max_repairs:
            mission.advance(CodingStage.REPAIR)
        else:
            mission.fail("review or security evidence failed and repair budget is exhausted")

    def finalize_with_ci(
        self,
        mission: CodingMission,
        *,
        impact: ChangeImpact,
        risk: DiffRiskAssessment,
        ci_jobs: Iterable[CIJobEvidence],
        validation_passed: bool,
        approval_granted: bool = False,
        unresolved_findings: Iterable[str] = (),
    ) -> CodingCoordinatorSnapshot:
        if mission.stage != CodingStage.CI:
            raise CodingMissionError("CI finalization requires mission to be in CI stage")

        evidence = RepositoryIntelligence.build_pr_evidence(
            impact=impact,
            risk=risk,
            validation_passed=validation_passed,
            self_review_passed=mission.review_passed,
            security_review_passed=mission.security_passed,
            ci_passed=True,
            unresolved_findings=unresolved_findings,
        )
        result = CodingCIOrchestrator.route(
            mission,
            ci_jobs,
            diff_risk=risk.risk,
            approval_granted=approval_granted,
            pr_evidence=evidence,
        )
        if result.pr_ready:
            mission.advance(CodingStage.READY)
            mission.require_ready()
        elif result.next_stage == CodingStage.REPAIR:
            mission.stage = CodingStage.REPAIR
        elif result.next_stage == CodingStage.FAILED:
            mission.fail(result.reason)

        return CodingCoordinatorSnapshot(
            stage=mission.stage,
            impact=impact,
            risk=risk,
            plan=(),
            validation_passed=validation_passed,
            pr_evidence=evidence,
            ci_result=result,
            ready=mission.ready,
            reason=result.reason,
        )


__all__ = ["AutonomousCodingCoordinator", "CodingCoordinatorSnapshot"]
