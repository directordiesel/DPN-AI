from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.automation_runtime_v9 import RetryPolicy, WorkflowStep, WorkflowStepStatus


MAX_CHAIN_STEPS = 512


@dataclass(frozen=True)
class RetryPlan:
    step_id: str
    retry: bool
    retry_number: int | None
    delay_seconds: int | None
    retries_remaining: int
    fresh_approval_required: bool
    reason: str


class AutomationChainError(ValueError):
    """Raised when deterministic workflow-chain planning fails closed."""


def _validate_steps(steps: Iterable[WorkflowStep]) -> tuple[WorkflowStep, ...]:
    values = tuple(steps)
    if len(values) > MAX_CHAIN_STEPS:
        raise AutomationChainError("workflow chain exceeds configured step limit")
    ids = [str(step.step_id or "").strip() for step in values]
    if any(not step_id for step_id in ids):
        raise AutomationChainError("workflow chain contains a blank step id")
    if len(ids) != len(set(ids)):
        raise AutomationChainError("workflow chain contains duplicate step ids")
    known = set(ids)
    for step in values:
        for dependency in step.depends_on:
            if dependency not in known:
                raise AutomationChainError(f"workflow step has unknown dependency: {dependency}")
    return values


def ready_step_ids(steps: Iterable[WorkflowStep]) -> tuple[str, ...]:
    """Return deterministic pending steps whose dependencies all succeeded."""

    values = _validate_steps(steps)
    by_id = {step.step_id: step for step in values}
    ready: list[str] = []
    for step in values:
        if step.status != WorkflowStepStatus.PENDING:
            continue
        if all(by_id[dependency].status == WorkflowStepStatus.SUCCEEDED for dependency in step.depends_on):
            ready.append(step.step_id)
    return tuple(ready)


def retry_plan(step: WorkflowStep, policy: RetryPolicy, *, approval_granted_for_attempt: bool = False) -> RetryPlan:
    """Plan one retry without carrying approval across attempts.

    A failed destructive or approval-required step may still be within its retry
    budget, but every new attempt requires a fresh approval. This planner does
    not grant approval and never converts a previous approval into a reusable
    session/persistent grant.
    """

    if not isinstance(step, WorkflowStep):
        raise AutomationChainError("step must be WorkflowStep")
    normalized = policy.normalized()
    retries_used = max(0, int(step.attempts) - 1)
    allowed_by_budget = step.status == WorkflowStepStatus.FAILED and retries_used < normalized.max_retries
    requires_fresh_approval = bool(step.destructive or step.approval_required)

    retry_number = retries_used + 1 if allowed_by_budget else None
    delay = normalized.delay_for_retry(retry_number) if retry_number is not None else None
    retries_remaining = max(0, normalized.max_retries - retries_used)

    if not allowed_by_budget:
        return RetryPlan(
            step_id=step.step_id,
            retry=False,
            retry_number=None,
            delay_seconds=None,
            retries_remaining=retries_remaining,
            fresh_approval_required=requires_fresh_approval,
            reason="retry budget exhausted or step is not failed",
        )

    if requires_fresh_approval and not approval_granted_for_attempt:
        return RetryPlan(
            step_id=step.step_id,
            retry=False,
            retry_number=retry_number,
            delay_seconds=delay,
            retries_remaining=retries_remaining,
            fresh_approval_required=True,
            reason="fresh approval required for retry attempt",
        )

    return RetryPlan(
        step_id=step.step_id,
        retry=True,
        retry_number=retry_number,
        delay_seconds=delay,
        retries_remaining=retries_remaining,
        fresh_approval_required=requires_fresh_approval,
        reason="retry permitted within bounded policy",
    )


def blocked_by_terminal_failure(steps: Iterable[WorkflowStep]) -> tuple[str, ...]:
    """Return pending steps transitively blocked by failed/blocked/cancelled dependencies."""

    values = _validate_steps(steps)
    by_id = {step.step_id: step for step in values}
    blocked: set[str] = set()
    changed = True
    terminal_bad = {
        WorkflowStepStatus.FAILED,
        WorkflowStepStatus.BLOCKED,
        WorkflowStepStatus.CANCELLED,
    }
    while changed:
        changed = False
        for step in values:
            if step.status != WorkflowStepStatus.PENDING or step.step_id in blocked:
                continue
            if any(
                by_id[dep].status in terminal_bad or dep in blocked
                for dep in step.depends_on
            ):
                blocked.add(step.step_id)
                changed = True
    return tuple(step.step_id for step in values if step.step_id in blocked)


__all__ = [
    "AutomationChainError",
    "MAX_CHAIN_STEPS",
    "RetryPlan",
    "blocked_by_terminal_failure",
    "ready_step_ids",
    "retry_plan",
]
