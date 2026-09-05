import pytest

from app.automation_chain_v9 import (
    AutomationChainError,
    MAX_CHAIN_STEPS,
    blocked_by_terminal_failure,
    ready_step_ids,
    retry_plan,
)
from app.automation_runtime_v9 import RetryPolicy, WorkflowStep, WorkflowStepStatus


def test_ready_steps_follow_dependency_chain_deterministically():
    first = WorkflowStep("first", "First", "run", status=WorkflowStepStatus.SUCCEEDED)
    second = WorkflowStep("second", "Second", "run", depends_on=["first"])
    third = WorkflowStep("third", "Third", "run", depends_on=["second"])
    parallel = WorkflowStep("parallel", "Parallel", "run")

    assert ready_step_ids([first, second, third, parallel]) == ("second", "parallel")


def test_failed_dependency_transitively_blocks_pending_chain():
    first = WorkflowStep("first", "First", "run", status=WorkflowStepStatus.FAILED)
    second = WorkflowStep("second", "Second", "run", depends_on=["first"])
    third = WorkflowStep("third", "Third", "run", depends_on=["second"])
    independent = WorkflowStep("independent", "Independent", "run")

    assert blocked_by_terminal_failure([first, second, third, independent]) == ("second", "third")


def test_retry_is_bounded_and_preserves_backoff():
    step = WorkflowStep("safe", "Safe", "run", status=WorkflowStepStatus.FAILED, attempts=1)
    policy = RetryPolicy(max_retries=2, backoff_seconds=10, max_backoff_seconds=15)

    plan = retry_plan(step, policy)
    assert plan.retry is True
    assert plan.retry_number == 1
    assert plan.delay_seconds == 10
    assert plan.retries_remaining == 2
    assert plan.fresh_approval_required is False

    step.attempts = 3
    exhausted = retry_plan(step, policy)
    assert exhausted.retry is False
    assert exhausted.retry_number is None


def test_destructive_retry_requires_fresh_approval_every_attempt():
    step = WorkflowStep(
        "delete",
        "Delete",
        "delete generated file",
        destructive=True,
        status=WorkflowStepStatus.FAILED,
        attempts=1,
    )
    policy = RetryPolicy(max_retries=3, backoff_seconds=5, max_backoff_seconds=20)

    blocked = retry_plan(step, policy)
    assert blocked.retry is False
    assert blocked.fresh_approval_required is True
    assert blocked.reason == "fresh approval required for retry attempt"

    approved = retry_plan(step, policy, approval_granted_for_attempt=True)
    assert approved.retry is True
    assert approved.fresh_approval_required is True

    # A later retry is a new attempt; prior approval cannot be silently reused.
    step.attempts = 2
    later = retry_plan(step, policy)
    assert later.retry is False
    assert later.retry_number == 2
    assert later.fresh_approval_required is True


def test_non_destructive_explicit_approval_also_requires_fresh_retry_approval():
    step = WorkflowStep(
        "publish",
        "Publish",
        "publish result",
        approval_required=True,
        status=WorkflowStepStatus.FAILED,
        attempts=1,
    )
    assert retry_plan(step, RetryPolicy(max_retries=1)).retry is False
    assert retry_plan(
        step,
        RetryPolicy(max_retries=1),
        approval_granted_for_attempt=True,
    ).retry is True


def test_unknown_dependency_and_duplicate_ids_fail_closed():
    with pytest.raises(AutomationChainError, match="unknown dependency"):
        ready_step_ids([WorkflowStep("a", "A", "run", depends_on=["missing"])])

    with pytest.raises(AutomationChainError, match="duplicate"):
        ready_step_ids([
            WorkflowStep("same", "One", "run"),
            WorkflowStep("same", "Two", "run"),
        ])


def test_chain_size_is_strictly_bounded():
    steps = [WorkflowStep(f"step-{index}", "Step", "run") for index in range(MAX_CHAIN_STEPS + 1)]
    with pytest.raises(AutomationChainError, match="step limit"):
        ready_step_ids(steps)
