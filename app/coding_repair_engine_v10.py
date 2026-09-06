from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.autonomous_coding_runtime_v10 import CodingMission, CodingMissionError, CodingStage, ValidationEvidence
from app.coding_repository_intelligence_v10 import DiffRisk


class FailureKind(str, Enum):
    SYNTAX = "syntax"
    TEST = "test"
    STATIC_ANALYSIS = "static_analysis"
    DEPENDENCY = "dependency"
    SECURITY = "security"
    CI = "ci"
    UNKNOWN = "unknown"


class RepairDisposition(str, Enum):
    REPAIR = "repair"
    ESCALATE = "escalate"
    FAIL = "fail"


@dataclass(frozen=True)
class ChangePlanStep:
    order: int
    path: str
    action: str
    reason: str
    expected_tests: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.order < 1:
            raise CodingMissionError("change plan order must be positive")
        if not self.path.strip():
            raise CodingMissionError("change plan path is required")
        if self.action not in {"create", "update", "delete", "inspect"}:
            raise CodingMissionError("unsupported change plan action")
        if not self.reason.strip():
            raise CodingMissionError("change plan reason is required")


@dataclass(frozen=True)
class ValidationResult:
    name: str
    passed: bool
    output: str = ""
    exit_code: int | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise CodingMissionError("validation result name is required")
        if self.exit_code is not None and self.exit_code < 0:
            raise CodingMissionError("validation exit code must be non-negative")


@dataclass(frozen=True)
class FailureDiagnosis:
    kind: FailureKind
    summary: str
    repairable: bool
    affected_paths: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepairDecision:
    disposition: RepairDisposition
    reason: str
    next_stage: CodingStage


class CodingRepairEngine:
    """Deterministic repair policy for v10 coding missions.

    It never claims a repair succeeded. It translates recorded validation/CI
    evidence into a diagnosis and bounded next action while preserving approval
    boundaries for high-risk/security-sensitive changes.
    """

    @staticmethod
    def build_change_plan(steps: Iterable[ChangePlanStep]) -> tuple[ChangePlanStep, ...]:
        materialized = list(steps)
        if not materialized:
            raise CodingMissionError("at least one change plan step is required")
        for step in materialized:
            step.validate()
        orders = [step.order for step in materialized]
        if len(set(orders)) != len(orders):
            raise CodingMissionError("change plan step order must be unique")
        ordered = tuple(sorted(materialized, key=lambda item: item.order))
        if [step.order for step in ordered] != list(range(1, len(ordered) + 1)):
            raise CodingMissionError("change plan step order must be contiguous")
        return ordered

    @staticmethod
    def record_validation_results(mission: CodingMission, results: Iterable[ValidationResult]) -> bool:
        materialized = list(results)
        if not materialized:
            raise CodingMissionError("at least one validation result is required")
        all_passed = True
        for result in materialized:
            result.validate()
            mission.record_validation(
                ValidationEvidence(
                    name=result.name,
                    passed=bool(result.passed),
                    detail=result.output.strip(),
                )
            )
            all_passed = all_passed and bool(result.passed)
        return all_passed

    @staticmethod
    def diagnose(results: Iterable[ValidationResult]) -> FailureDiagnosis:
        failed = [result for result in results if not result.passed]
        if not failed:
            return FailureDiagnosis(FailureKind.UNKNOWN, "no failing validation evidence", False)

        combined = "\n".join((item.name + "\n" + item.output).lower() for item in failed)
        if "syntaxerror" in combined or "compile" in combined:
            kind = FailureKind.SYNTAX
        elif "security" in combined or "vulnerab" in combined or "secret" in combined:
            kind = FailureKind.SECURITY
        elif "dependency" in combined or "module not found" in combined or "modulenotfounderror" in combined:
            kind = FailureKind.DEPENDENCY
        elif "pytest" in combined or "assert" in combined or "test" in combined:
            kind = FailureKind.TEST
        elif "lint" in combined or "type check" in combined or "mypy" in combined or "ruff" in combined:
            kind = FailureKind.STATIC_ANALYSIS
        elif "github actions" in combined or "workflow" in combined or "ci" in combined:
            kind = FailureKind.CI
        else:
            kind = FailureKind.UNKNOWN

        repairable = kind in {
            FailureKind.SYNTAX,
            FailureKind.TEST,
            FailureKind.STATIC_ANALYSIS,
            FailureKind.DEPENDENCY,
            FailureKind.CI,
        }
        summary = f"{len(failed)} validation check(s) failed; classified as {kind.value}"
        evidence = tuple(item.name for item in failed)
        return FailureDiagnosis(kind, summary, repairable, evidence=evidence)

    @staticmethod
    def decide_repair(
        mission: CodingMission,
        diagnosis: FailureDiagnosis,
        *,
        diff_risk: DiffRisk,
        approval_granted: bool = False,
    ) -> RepairDecision:
        mission.validate()
        if diagnosis.kind == FailureKind.SECURITY or diff_risk == DiffRisk.CRITICAL:
            return RepairDecision(
                RepairDisposition.ESCALATE,
                "security-critical or critical-risk change requires human approval",
                CodingStage.FAILED,
            )
        if diff_risk == DiffRisk.HIGH and not approval_granted:
            return RepairDecision(
                RepairDisposition.ESCALATE,
                "high-risk repair requires approval before another edit",
                CodingStage.FAILED,
            )
        if not diagnosis.repairable:
            return RepairDecision(
                RepairDisposition.FAIL,
                "failure is not safely repairable from available evidence",
                CodingStage.FAILED,
            )
        if mission.repair_attempts >= mission.max_repairs:
            return RepairDecision(
                RepairDisposition.FAIL,
                "repair budget exhausted",
                CodingStage.FAILED,
            )
        return RepairDecision(
            RepairDisposition.REPAIR,
            f"bounded repair approved for {diagnosis.kind.value} failure",
            CodingStage.REPAIR,
        )


__all__ = [
    "ChangePlanStep",
    "CodingRepairEngine",
    "FailureDiagnosis",
    "FailureKind",
    "RepairDecision",
    "RepairDisposition",
    "ValidationResult",
]
