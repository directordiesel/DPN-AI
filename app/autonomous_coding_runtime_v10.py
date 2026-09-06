from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CodingMissionError(ValueError):
    """Raised when an autonomous coding mission violates its execution contract."""


class CodingStage(str, Enum):
    INSPECT = "inspect"
    PLAN = "plan"
    ISOLATE = "isolate"
    EDIT = "edit"
    VALIDATE = "validate"
    DIAGNOSE = "diagnose"
    REPAIR = "repair"
    REVIEW = "review"
    CI = "ci"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class ValidationEvidence:
    name: str
    passed: bool
    detail: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise CodingMissionError("validation name is required")


@dataclass
class CodingMission:
    mission_id: str
    repository: str
    objective: str
    max_repairs: int = 3
    stage: CodingStage = CodingStage.INSPECT
    affected_files: list[str] = field(default_factory=list)
    affected_tests: list[str] = field(default_factory=list)
    evidence: list[ValidationEvidence] = field(default_factory=list)
    repair_attempts: int = 0
    review_passed: bool = False
    security_passed: bool = False
    ci_passed: bool = False
    failure_reason: str = ""

    def validate(self) -> None:
        if not self.mission_id.strip():
            raise CodingMissionError("mission id is required")
        if not self.repository.strip():
            raise CodingMissionError("repository is required")
        if not self.objective.strip():
            raise CodingMissionError("objective is required")
        if isinstance(self.max_repairs, bool) or not isinstance(self.max_repairs, int) or not 0 <= self.max_repairs <= 20:
            raise CodingMissionError("max repairs must be between 0 and 20")

    def advance(self, next_stage: CodingStage) -> None:
        self.validate()
        allowed = {
            CodingStage.INSPECT: {CodingStage.PLAN, CodingStage.FAILED},
            CodingStage.PLAN: {CodingStage.ISOLATE, CodingStage.FAILED},
            CodingStage.ISOLATE: {CodingStage.EDIT, CodingStage.FAILED},
            CodingStage.EDIT: {CodingStage.VALIDATE, CodingStage.FAILED},
            CodingStage.VALIDATE: {CodingStage.REVIEW, CodingStage.DIAGNOSE, CodingStage.FAILED},
            CodingStage.DIAGNOSE: {CodingStage.REPAIR, CodingStage.FAILED},
            CodingStage.REPAIR: {CodingStage.VALIDATE, CodingStage.FAILED},
            CodingStage.REVIEW: {CodingStage.CI, CodingStage.REPAIR, CodingStage.FAILED},
            CodingStage.CI: {CodingStage.READY, CodingStage.DIAGNOSE, CodingStage.FAILED},
            CodingStage.READY: set(),
            CodingStage.FAILED: set(),
        }
        if next_stage not in allowed[self.stage]:
            raise CodingMissionError(f"invalid coding mission transition: {self.stage.value} -> {next_stage.value}")
        self.stage = next_stage

    def record_validation(self, evidence: ValidationEvidence) -> None:
        evidence.validate()
        self.evidence.append(evidence)

    def record_repair(self) -> None:
        if self.repair_attempts >= self.max_repairs:
            self.fail("repair budget exhausted")
            raise CodingMissionError("repair budget exhausted")
        self.repair_attempts += 1

    def mark_review(self, *, review_passed: bool, security_passed: bool) -> None:
        self.review_passed = bool(review_passed)
        self.security_passed = bool(security_passed)

    def mark_ci(self, passed: bool) -> None:
        self.ci_passed = bool(passed)

    def fail(self, reason: str) -> None:
        if not reason.strip():
            raise CodingMissionError("failure reason is required")
        self.failure_reason = reason.strip()
        self.stage = CodingStage.FAILED

    @property
    def ready(self) -> bool:
        return (
            self.stage == CodingStage.READY
            and self.review_passed
            and self.security_passed
            and self.ci_passed
            and bool(self.evidence)
            and all(item.passed for item in self.evidence)
        )

    def require_ready(self) -> None:
        if not self.ready:
            raise CodingMissionError("coding mission is not ready; required evidence is incomplete")


class AutonomousCodingRuntime:
    """Fail-closed orchestration contract for DPN AI v10 coding missions.

    This runtime records state and evidence; repository writes, tests, CI calls, and
    approvals remain delegated to governed tools. It prevents a mission from being
    declared ready unless review, security, CI, and validation evidence all pass.
    """

    def begin(self, mission: CodingMission) -> CodingMission:
        mission.validate()
        if mission.stage != CodingStage.INSPECT:
            raise CodingMissionError("new coding missions must start at inspect")
        return mission

    @staticmethod
    def route_validation_result(mission: CodingMission) -> CodingStage:
        recent = mission.evidence[-1] if mission.evidence else None
        return CodingStage.REVIEW if recent is not None and recent.passed else CodingStage.DIAGNOSE

    @staticmethod
    def route_ci_result(mission: CodingMission) -> CodingStage:
        return CodingStage.READY if mission.ci_passed else CodingStage.DIAGNOSE


__all__ = [
    "AutonomousCodingRuntime",
    "CodingMission",
    "CodingMissionError",
    "CodingStage",
    "ValidationEvidence",
]
