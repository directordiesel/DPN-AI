from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AutomationMode(str, Enum):
    ONCE = "once"
    RECURRING = "recurring"
    CONDITION = "condition"


class AutomationLifecycle(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


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


@dataclass(frozen=True)
class ConditionProviderSpec:
    key: str
    operators: tuple[str, ...]
    max_payload_bytes: int = 65_536
    requires_network: bool = False

    def validate(self) -> None:
        key = self.key.strip()
        if not key:
            raise ValueError("Condition provider key is required")
        if not self.operators:
            raise ValueError("Condition provider must declare at least one operator")
        if any(not operator.strip() for operator in self.operators):
            raise ValueError("Condition provider operators cannot be blank")
        if len(set(self.operators)) != len(self.operators):
            raise ValueError("Condition provider operators must be unique")
        if not 1 <= int(self.max_payload_bytes) <= 1_048_576:
            raise ValueError("max_payload_bytes must be between 1 and 1048576")


@dataclass(frozen=True)
class ConditionEvaluation:
    provider: str
    operator: str
    matched: bool
    evidence: tuple[str, ...] = ()
    observed_value: Any = None


class ConditionProviderRegistry:
    """Fail-closed registry for condition-capable automation providers.

    The registry is intentionally deterministic and contains no provider I/O.
    External adapters must register an explicit provider contract and supply a
    verified ConditionEvaluation after performing any permission/network checks.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ConditionProviderSpec] = {}

    def register(self, spec: ConditionProviderSpec) -> None:
        spec.validate()
        key = spec.key.strip().lower()
        if key in self._providers:
            raise ValueError(f"Condition provider already registered: {key}")
        self._providers[key] = spec

    def get(self, key: str) -> ConditionProviderSpec:
        normalized = key.strip().lower()
        if normalized not in self._providers:
            raise ValueError(f"Unknown condition provider: {normalized or '<blank>'}")
        return self._providers[normalized]

    def validate_request(self, provider: str, operator: str, payload_size_bytes: int) -> dict[str, Any]:
        spec = self.get(provider)
        op = operator.strip()
        if op not in spec.operators:
            raise ValueError(f"Unsupported condition operator for {spec.key}: {op or '<blank>'}")
        size = int(payload_size_bytes)
        if size < 0:
            raise ValueError("payload_size_bytes cannot be negative")
        if size > spec.max_payload_bytes:
            raise ValueError(
                f"Condition payload exceeds provider limit: {size} > {spec.max_payload_bytes}"
            )
        return {
            "ok": True,
            "provider": spec.key,
            "operator": op,
            "max_payload_bytes": spec.max_payload_bytes,
            "requires_network": spec.requires_network,
        }

    def accept_evaluation(self, evaluation: ConditionEvaluation) -> dict[str, Any]:
        spec = self.get(evaluation.provider)
        if evaluation.operator not in spec.operators:
            raise ValueError(f"Unsupported condition operator for {spec.key}: {evaluation.operator}")
        evidence = [item.strip() for item in evaluation.evidence if item.strip()]
        if evaluation.matched and not evidence:
            raise ValueError("Matched condition evaluations require evidence")
        return {
            "ok": True,
            "provider": spec.key,
            "operator": evaluation.operator,
            "matched": bool(evaluation.matched),
            "evidence": evidence,
            "observed_value": evaluation.observed_value,
        }


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
    automation definitions and provides dependency, retry, approval, overlap,
    condition-provider, lifecycle, and evidence rules that the existing
    AutomationEngine can adopt incrementally.
    """

    _LIFECYCLE_TRANSITIONS: dict[AutomationLifecycle, set[AutomationLifecycle]] = {
        AutomationLifecycle.ACTIVE: {
            AutomationLifecycle.PAUSED,
            AutomationLifecycle.CANCELLED,
            AutomationLifecycle.COMPLETED,
        },
        AutomationLifecycle.PAUSED: {
            AutomationLifecycle.ACTIVE,
            AutomationLifecycle.CANCELLED,
        },
        AutomationLifecycle.CANCELLED: set(),
        AutomationLifecycle.COMPLETED: set(),
    }

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
    def transition_lifecycle(
        current: AutomationLifecycle,
        target: AutomationLifecycle,
        *,
        active_step_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        active = sorted({item.strip() for item in (active_step_ids or []) if item.strip()})
        allowed = AutomationWorkflowRuntime._LIFECYCLE_TRANSITIONS[current]
        if target not in allowed:
            raise ValueError(f"Invalid automation lifecycle transition: {current.value} -> {target.value}")
        if target == AutomationLifecycle.COMPLETED and active:
            raise ValueError("Automation cannot complete while workflow steps are active")
        return {
            "ok": True,
            "from": current.value,
            "to": target.value,
            "active_step_ids": active,
            "cancel_running_steps": target == AutomationLifecycle.CANCELLED and bool(active),
            "dispatch_allowed": target == AutomationLifecycle.ACTIVE,
        }

    @staticmethod
    def dispatch_allowed(lifecycle: AutomationLifecycle, condition_matched: bool | None = None) -> bool:
        if lifecycle != AutomationLifecycle.ACTIVE:
            return False
        if condition_matched is None:
            return True
        return bool(condition_matched)

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
