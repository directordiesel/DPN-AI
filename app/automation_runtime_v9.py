from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AutomationMode(str, Enum):
    ONCE = "once"
    RECURRING = "recurring"
    CONDITION = "condition"


class OverlapPolicy(str, Enum):
    SKIP = "skip"
    QUEUE = "queue"
    REPLACE = "replace"


class WorkflowStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_seconds: int = 60
    max_backoff_seconds: int = 3600

    def normalized(self) -> "RetryPolicy":
        retries = max(0, min(int(self.max_retries), 10))
        base = max(5, min(int(self.backoff_seconds), 86_400))
        cap = max(base, min(int(self.max_backoff_seconds), 86_400))
        return RetryPolicy(retries, base, cap)

    def delay_for_retry(self, retry_number: int) -> int:
        policy = self.normalized()
        number = max(1, int(retry_number))
        return min(policy.backoff_seconds * (2 ** (number - 1)), policy.max_backoff_seconds)


@dataclass
class WorkflowStep:
    step_id: str
    title: str
    action: str
    depends_on: list[str] = field(default_factory=list)
    destructive: bool = False
    approval_required: bool = False
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    attempts: int = 0
    evidence: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class AutomationDefinition:
    name: str
    objective: str
    mode: AutomationMode
    schedule: str = ""
    condition: str = ""
    overlap_policy: OverlapPolicy = OverlapPolicy.SKIP
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    max_runtime_seconds: int = 900
    steps: list[WorkflowStep] = field(default_factory=list)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Automation name is required")
        if not self.objective.strip():
            raise ValueError("Automation objective is required")
        if self.mode in {AutomationMode.ONCE, AutomationMode.RECURRING} and not self.schedule.strip():
            raise ValueError("Scheduled automations require schedule")
        if self.mode == AutomationMode.CONDITION and not self.condition.strip():
            raise ValueError("Condition automations require condition")
        if not 30 <= int(self.max_runtime_seconds) <= 86_400:
            raise ValueError("max_runtime_seconds must be between 30 and 86400")

        ids = [step.step_id.strip() for step in self.steps]
        if any(not item for item in ids):
            raise ValueError("Workflow step IDs cannot be blank")
        if len(ids) != len(set(ids)):
            raise ValueError("Workflow step IDs must be unique")
        seen: set[str] = set()
        for step in self.steps:
            for dependency in step.depends_on:
                if dependency not in seen:
                    raise ValueError(f"Step {step.step_id} has unknown or forward dependency: {dependency}")
            seen.add(step.step_id)

    @property
    def automation_id(self) -> str:
        material = "|".join(
            [self.name.strip(), self.objective.strip(), self.mode.value, self.schedule.strip(), self.condition.strip()]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


class AutomationWorkflowRuntime:
    """Deterministic v9 scheduler/workflow state evaluator.

    This layer does not replace the persisted scheduler. It normalizes richer v9
    automation definitions and provides dependency, retry, approval, overlap, and
    evidence rules that the existing AutomationEngine can adopt incrementally.
    """

    def normalize_definition(self, definition: AutomationDefinition) -> dict[str, Any]:
        definition.validate()
        retry = definition.retry_policy.normalized()
        return {
            "ok": True,
            "automation_id": definition.automation_id,
            "name": definition.name.strip(),
            "objective": definition.objective.strip(),
            "mode": definition.mode.value,
            "schedule": definition.schedule.strip(),
            "condition": definition.condition.strip(),
            "overlap_policy": definition.overlap_policy.value,
            "max_runtime_seconds": int(definition.max_runtime_seconds),
            "retry_policy": {
                "max_retries": retry.max_retries,
                "backoff_seconds": retry.backoff_seconds,
                "max_backoff_seconds": retry.max_backoff_seconds,
            },
            "steps": [self._step_payload(step) for step in definition.steps],
        }

    @staticmethod
    def _step_payload(step: WorkflowStep) -> dict[str, Any]:
        return {
            "step_id": step.step_id,
            "title": step.title,
            "action": step.action,
            "depends_on": list(step.depends_on),
            "destructive": bool(step.destructive),
            "approval_required": bool(step.approval_required or step.destructive),
            "status": step.status.value,
            "attempts": int(step.attempts),
            "evidence": list(step.evidence),
            "error": step.error,
        }

    @staticmethod
    def can_start(step: WorkflowStep, steps: list[WorkflowStep]) -> bool:
        by_id = {item.step_id: item for item in steps}
        return all(by_id[dep].status == WorkflowStepStatus.SUCCEEDED for dep in step.depends_on)

    @staticmethod
    def block_dependents(steps: list[WorkflowStep], failed_step_id: str) -> list[str]:
        blocked: list[str] = []
        changed = True
        while changed:
            changed = False
            for step in steps:
                if step.status != WorkflowStepStatus.PENDING:
                    continue
                if failed_step_id in step.depends_on or any(dep in blocked for dep in step.depends_on):
                    step.status = WorkflowStepStatus.BLOCKED
                    blocked.append(step.step_id)
                    changed = True
        return blocked

    @staticmethod
    def retry_decision(step: WorkflowStep, policy: RetryPolicy) -> dict[str, Any]:
        normalized = policy.normalized()
        retries_used = max(0, step.attempts - 1)
        retry_number = retries_used + 1
        allowed = step.status == WorkflowStepStatus.FAILED and retries_used < normalized.max_retries
        return {
            "retry": allowed,
            "retry_number": retry_number if allowed else None,
            "delay_seconds": normalized.delay_for_retry(retry_number) if allowed else None,
            "retries_remaining": max(0, normalized.max_retries - retries_used),
        }

    @staticmethod
    def completion_summary(steps: list[WorkflowStep]) -> dict[str, Any]:
        succeeded = [step.step_id for step in steps if step.status == WorkflowStepStatus.SUCCEEDED]
        failed = [step.step_id for step in steps if step.status == WorkflowStepStatus.FAILED]
        blocked = [step.step_id for step in steps if step.status == WorkflowStepStatus.BLOCKED]
        cancelled = [step.step_id for step in steps if step.status == WorkflowStepStatus.CANCELLED]
        evidence_count = sum(len(step.evidence) for step in steps)
        complete = bool(steps) and len(succeeded) == len(steps)
        return {
            "ok": complete,
            "complete": complete,
            "succeeded": succeeded,
            "failed": failed,
            "blocked": blocked,
            "cancelled": cancelled,
            "evidence_count": evidence_count,
            "evidence_required_for_success": True,
        }
