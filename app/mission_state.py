from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from app.intelligence_runtime import ReasoningPlan, StepStatus


class MissionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MissionState:
    mission_id: str
    objective: str
    status: MissionStatus = MissionStatus.CREATED
    current_step_id: str | None = None
    completed_step_ids: list[str] = field(default_factory=list)
    failed_step_ids: list[str] = field(default_factory=list)
    blocked_step_ids: list[str] = field(default_factory=list)
    total_attempts: int = 0
    tool_calls: int = 0
    generated_files: list[str] = field(default_factory=list)
    reviewer_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_plan(cls, mission_id: str, plan: ReasoningPlan) -> "MissionState":
        if not mission_id.strip():
            raise ValueError("mission_id is required")
        return cls(mission_id=mission_id.strip(), objective=plan.objective)

    def refresh(self, plan: ReasoningPlan) -> "MissionState":
        self.completed_step_ids = [step.id for step in plan.steps if step.status == StepStatus.SUCCEEDED]
        self.failed_step_ids = [step.id for step in plan.steps if step.status == StepStatus.FAILED]
        self.blocked_step_ids = [step.id for step in plan.steps if step.status == StepStatus.BLOCKED]
        self.total_attempts = sum(step.attempts for step in plan.steps)
        self.tool_calls = sum((step.result.tool_count if step.result else 0) for step in plan.steps)
        self.generated_files = list(dict.fromkeys(
            path
            for step in plan.steps
            if step.result
            for path in step.result.generated_files
        ))
        confidences = [step.review.confidence for step in plan.steps if step.review]
        self.reviewer_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0

        running = next((step.id for step in plan.steps if step.status in {StepStatus.READY, StepStatus.RUNNING}), None)
        self.current_step_id = running

        if any(step.status == StepStatus.CANCELLED for step in plan.steps):
            self.status = MissionStatus.CANCELLED
        elif len(self.completed_step_ids) == len(plan.steps) and plan.steps:
            self.status = MissionStatus.SUCCEEDED
        elif self.failed_step_ids and self.completed_step_ids:
            self.status = MissionStatus.PARTIAL
        elif self.failed_step_ids or self.blocked_step_ids:
            self.status = MissionStatus.FAILED
        elif running or any(step.status != StepStatus.PENDING for step in plan.steps):
            self.status = MissionStatus.RUNNING
        else:
            self.status = MissionStatus.CREATED
        return self

    def summary(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status.value,
            "objective": self.objective,
            "progress": {
                "completed": len(self.completed_step_ids),
                "failed": len(self.failed_step_ids),
                "blocked": len(self.blocked_step_ids),
            },
            "current_step_id": self.current_step_id,
            "attempts": self.total_attempts,
            "tool_calls": self.tool_calls,
            "generated_files": list(self.generated_files),
            "reviewer_confidence": self.reviewer_confidence,
        }
