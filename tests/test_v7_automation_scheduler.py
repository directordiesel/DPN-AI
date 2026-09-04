from plugins.automation_scheduler_v7 import evaluate_automation_run_v7, plan_automation_v7


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
