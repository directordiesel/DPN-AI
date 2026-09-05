from plugins.automation_scheduler_v7 import (
    evaluate_automation_run_v7,
    evaluate_workflow_v9,
    plan_automation_v7,
    plan_automation_v9,
)


def test_automation_plan_requires_objective():
    assert plan_automation_v7("")["ok"] is False


def test_recurring_automation_requires_schedule():
    result = plan_automation_v7("Audit repositories", mode="recurring")
    assert result["ok"] is False
    assert "schedule" in result["error"]


def test_condition_automation_requires_condition():
    result = plan_automation_v7("Watch CI", mode="condition")
    assert result["ok"] is False
    assert "condition" in result["error"]


def test_automation_plan_bounds_retries_runtime_and_preserves_safety():
    result = plan_automation_v7(
        "Audit repositories",
        mode="recurring",
        schedule="0 * * * *",
        max_retries=99,
        retry_backoff_seconds=1,
        max_runtime_seconds=999999,
        overlap_policy="replace",
    )
    assert result["ok"] is True
    policy = result["execution_policy"]
    assert policy["max_retries"] == 10
    assert policy["retry_backoff_seconds"] == 5
    assert policy["max_runtime_seconds"] == 86400
    assert policy["overlap_policy"] == "replace"
    assert policy["checkpoint_before_side_effects"] is True
    assert policy["resume_after_restart"] is True
    assert policy["idempotency_required"] is True
    assert policy["failure_evidence_required"] is True


def test_success_requires_persisted_terminal_evidence():
    incomplete = evaluate_automation_run_v7({
        "status": "success",
        "started_at": "2026-09-04T10:00:00Z",
        "finished_at": "2026-09-04T10:01:00Z",
        "persisted": True,
    })
    assert incomplete["ready"] is False

    complete = evaluate_automation_run_v7({
        "status": "success",
        "started_at": "2026-09-04T10:00:00Z",
        "finished_at": "2026-09-04T10:01:00Z",
        "persisted": True,
        "evidence": {"checks": 4, "result": "passed"},
    })
    assert complete["ready"] is True


def test_terminal_failure_remains_auditable_not_successful():
    result = evaluate_automation_run_v7({
        "status": "failed",
        "started_at": "2026-09-04T10:00:00Z",
        "finished_at": "2026-09-04T10:01:00Z",
        "persisted": True,
        "evidence": {"error": "dependency unavailable"},
    })
    assert result["ready"] is False
    assert result["failure_recorded"] is True


def test_v9_plan_supports_chained_steps_and_destructive_approval():
    result = plan_automation_v9(
        name="CI repair workflow",
        objective="Diagnose a failed CI run and prepare a safe repair",
        mode="recurring",
        schedule="hourly",
        steps=[
            {"step_id": "inspect", "title": "Inspect CI", "action": "read logs"},
            {
                "step_id": "repair",
                "title": "Prepare repair",
                "action": "patch code",
                "depends_on": ["inspect"],
                "destructive": True,
            },
        ],
    )
    assert result["ok"] is True
    assert result["engine"] == "dpn-automation-workflow-v9"
    assert result["steps"][1]["depends_on"] == ["inspect"]
    assert result["steps"][1]["approval_required"] is True
    assert result["persistent_scheduler_compatibility"]["legacy_interval_daily_engine_preserved"] is True


def test_v9_plan_rejects_forward_dependency():
    result = plan_automation_v9(
        name="bad workflow",
        objective="Reject unsafe dependency order",
        mode="once",
        schedule="2026-09-05T12:00:00Z",
        steps=[
            {"step_id": "first", "action": "one", "depends_on": ["second"]},
            {"step_id": "second", "action": "two"},
        ],
    )
    assert result["ok"] is False
    assert "forward dependency" in result["error"]


def test_v9_condition_watch_is_explicit_about_provider_requirement():
    result = plan_automation_v9(
        name="CI condition watch",
        objective="Run when CI becomes red",
        mode="condition",
        condition="CI status is failure",
    )
    assert result["ok"] is True
    compatibility = result["persistent_scheduler_compatibility"]
    assert compatibility["condition_execution_requires_condition_provider"] is True
    assert compatibility["unsupported_runtime_paths_fail_closed"] is True


def test_v9_workflow_completion_requires_all_steps_succeeded():
    incomplete = evaluate_workflow_v9([
        {"step_id": "inspect", "status": "succeeded", "evidence": ["logs captured"]},
        {"step_id": "verify", "status": "failed", "evidence": ["tests red"]},
    ])
    assert incomplete["ok"] is False
    assert incomplete["failed"] == ["verify"]

    complete = evaluate_workflow_v9([
        {"step_id": "inspect", "status": "succeeded", "evidence": ["logs captured"]},
        {"step_id": "verify", "status": "succeeded", "evidence": ["tests green"]},
    ])
    assert complete["ok"] is True
    assert complete["evidence_count"] == 2
