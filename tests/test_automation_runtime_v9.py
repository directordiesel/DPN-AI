import pytest

from app.automation_runtime_v9 import (
    AutomationDefinition,
    AutomationLifecycle,
    AutomationMode,
    AutomationWorkflowRuntime,
    ConditionEvaluation,
    ConditionProviderRegistry,
    ConditionProviderSpec,
    OverlapPolicy,
    RetryPolicy,
    WorkflowStep,
    WorkflowStepStatus,
)


def test_normalizes_recurring_definition():
    runtime = AutomationWorkflowRuntime()
    definition = AutomationDefinition(
        name="Repo Health",
        objective="Inspect repository health",
        mode=AutomationMode.RECURRING,
        schedule="hourly",
        overlap_policy=OverlapPolicy.SKIP,
        steps=[WorkflowStep("inspect", "Inspect", "inspect repository")],
    )
    result = runtime.normalize_definition(definition)
    assert result["ok"] is True
    assert result["mode"] == "recurring"
    assert result["overlap_policy"] == "skip"
    assert len(result["automation_id"]) == 24


def test_condition_requires_condition():
    definition = AutomationDefinition(
        name="CI Watch",
        objective="React to CI failures",
        mode=AutomationMode.CONDITION,
    )
    with pytest.raises(ValueError, match="require condition"):
        definition.validate()


def test_rejects_forward_dependency():
    definition = AutomationDefinition(
        name="Chain",
        objective="Run a chain",
        mode=AutomationMode.ONCE,
        schedule="2026-09-05T04:00:00Z",
        steps=[
            WorkflowStep("second", "Second", "run second", depends_on=["first"]),
            WorkflowStep("first", "First", "run first"),
        ],
    )
    with pytest.raises(ValueError, match="unknown or forward dependency"):
        definition.validate()


def test_destructive_step_requires_approval_in_payload():
    runtime = AutomationWorkflowRuntime()
    definition = AutomationDefinition(
        name="Cleanup",
        objective="Clean generated files",
        mode=AutomationMode.ONCE,
        schedule="now",
        steps=[WorkflowStep("delete", "Delete", "delete generated file", destructive=True)],
    )
    payload = runtime.normalize_definition(definition)
    assert payload["steps"][0]["approval_required"] is True


def test_dependency_readiness_and_block_propagation():
    runtime = AutomationWorkflowRuntime()
    first = WorkflowStep("first", "First", "run", status=WorkflowStepStatus.FAILED)
    second = WorkflowStep("second", "Second", "run", depends_on=["first"])
    third = WorkflowStep("third", "Third", "run", depends_on=["second"])
    assert runtime.can_start(second, [first, second, third]) is False
    blocked = runtime.block_dependents([first, second, third], "first")
    assert blocked == ["second", "third"]
    assert second.status == WorkflowStepStatus.BLOCKED
    assert third.status == WorkflowStepStatus.BLOCKED


def test_retry_backoff_is_bounded_exponential():
    runtime = AutomationWorkflowRuntime()
    policy = RetryPolicy(max_retries=3, backoff_seconds=10, max_backoff_seconds=25)
    step = WorkflowStep("test", "Test", "run", status=WorkflowStepStatus.FAILED, attempts=1)
    first = runtime.retry_decision(step, policy)
    assert first["retry"] is True
    assert first["delay_seconds"] == 10

    step.attempts = 3
    third = runtime.retry_decision(step, policy)
    assert third["retry"] is True
    assert third["delay_seconds"] == 25

    step.attempts = 4
    done = runtime.retry_decision(step, policy)
    assert done["retry"] is False


def test_completion_requires_every_step_to_succeed():
    runtime = AutomationWorkflowRuntime()
    steps = [
        WorkflowStep("one", "One", "run", status=WorkflowStepStatus.SUCCEEDED, evidence=["verified"]),
        WorkflowStep("two", "Two", "run", status=WorkflowStepStatus.SUCCEEDED, evidence=["verified"]),
    ]
    result = runtime.completion_summary(steps)
    assert result["complete"] is True
    assert result["evidence_count"] == 2

    steps[1].status = WorkflowStepStatus.FAILED
    result = runtime.completion_summary(steps)
    assert result["complete"] is False
    assert result["failed"] == ["two"]


def test_condition_provider_registry_is_explicit_and_fail_closed():
    registry = ConditionProviderRegistry()
    registry.register(
        ConditionProviderSpec(
            key="github-ci",
            operators=("failed", "changed"),
            max_payload_bytes=2048,
            requires_network=True,
        )
    )

    request = registry.validate_request("github-ci", "failed", 1024)
    assert request["ok"] is True
    assert request["requires_network"] is True

    with pytest.raises(ValueError, match="Unknown condition provider"):
        registry.validate_request("unregistered", "failed", 1)
    with pytest.raises(ValueError, match="Unsupported condition operator"):
        registry.validate_request("github-ci", "deleted", 1)
    with pytest.raises(ValueError, match="exceeds provider limit"):
        registry.validate_request("github-ci", "failed", 4096)


def test_matched_condition_requires_evidence():
    registry = ConditionProviderRegistry()
    registry.register(ConditionProviderSpec(key="health", operators=("degraded",)))

    with pytest.raises(ValueError, match="require evidence"):
        registry.accept_evaluation(
            ConditionEvaluation(provider="health", operator="degraded", matched=True)
        )

    result = registry.accept_evaluation(
        ConditionEvaluation(
            provider="health",
            operator="degraded",
            matched=True,
            evidence=("probe=failed",),
            observed_value="offline",
        )
    )
    assert result["matched"] is True
    assert result["evidence"] == ["probe=failed"]


def test_automation_lifecycle_pause_resume_cancel_and_terminal_guards():
    runtime = AutomationWorkflowRuntime()

    paused = runtime.transition_lifecycle(AutomationLifecycle.ACTIVE, AutomationLifecycle.PAUSED)
    assert paused["dispatch_allowed"] is False
    assert runtime.dispatch_allowed(AutomationLifecycle.PAUSED) is False

    resumed = runtime.transition_lifecycle(AutomationLifecycle.PAUSED, AutomationLifecycle.ACTIVE)
    assert resumed["dispatch_allowed"] is True
    assert runtime.dispatch_allowed(AutomationLifecycle.ACTIVE, condition_matched=True) is True
    assert runtime.dispatch_allowed(AutomationLifecycle.ACTIVE, condition_matched=False) is False

    cancelled = runtime.transition_lifecycle(
        AutomationLifecycle.ACTIVE,
        AutomationLifecycle.CANCELLED,
        active_step_ids=["download", "verify", "download"],
    )
    assert cancelled["cancel_running_steps"] is True
    assert cancelled["active_step_ids"] == ["download", "verify"]

    with pytest.raises(ValueError, match="Invalid automation lifecycle transition"):
        runtime.transition_lifecycle(AutomationLifecycle.CANCELLED, AutomationLifecycle.ACTIVE)


def test_automation_cannot_complete_with_active_steps():
    runtime = AutomationWorkflowRuntime()
    with pytest.raises(ValueError, match="cannot complete while workflow steps are active"):
        runtime.transition_lifecycle(
            AutomationLifecycle.ACTIVE,
            AutomationLifecycle.COMPLETED,
            active_step_ids=["still-running"],
        )
