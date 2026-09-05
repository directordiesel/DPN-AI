from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.automation_runtime_v9 import (
    AutomationDefinition,
    AutomationMode,
    AutomationWorkflowRuntime,
    OverlapPolicy,
    RetryPolicy,
    WorkflowStep,
    WorkflowStepStatus,
)

_ALLOWED_MODES = {"once", "recurring", "condition"}
_ALLOWED_POLICIES = {"skip", "queue", "replace"}
_V9_RUNTIME = AutomationWorkflowRuntime()


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


def plan_automation_v7(
    objective: str,
    mode: str = "recurring",
    schedule: str = "",
    condition: str = "",
    max_retries: int = 3,
    retry_backoff_seconds: int = 60,
    max_runtime_seconds: int = 900,
    overlap_policy: str = "skip",
    approval_required: bool = True,
) -> dict[str, Any]:
    objective = str(objective or "").strip()
    if not objective:
        return {"ok": False, "error": "objective is required"}

    normalized_mode = str(mode or "recurring").strip().lower()
    if normalized_mode not in _ALLOWED_MODES:
        return {"ok": False, "error": f"unsupported mode: {normalized_mode}"}

    schedule = str(schedule or "").strip()
    condition = str(condition or "").strip()
    if normalized_mode in {"once", "recurring"} and not schedule:
        return {"ok": False, "error": "schedule is required for once or recurring automations"}
    if normalized_mode == "condition" and not condition:
        return {"ok": False, "error": "condition is required for condition automations"}

    overlap = str(overlap_policy or "skip").strip().lower()
    if overlap not in _ALLOWED_POLICIES:
        overlap = "skip"

    retries = _bounded_int(max_retries, 3, 0, 10)
    backoff = _bounded_int(retry_backoff_seconds, 60, 5, 86_400)
    runtime = _bounded_int(max_runtime_seconds, 900, 30, 86_400)

    return {
        "ok": True,
        "engine": "dpn-automation-scheduler-v7",
        "objective": objective,
        "mode": normalized_mode,
        "schedule": schedule,
        "condition": condition,
        "execution_policy": {
            "max_retries": retries,
            "retry_backoff_seconds": backoff,
            "max_runtime_seconds": runtime,
            "overlap_policy": overlap,
            "approval_required": bool(approval_required),
            "persistent_run_history": True,
            "checkpoint_before_side_effects": True,
            "resume_after_restart": True,
            "idempotency_required": True,
            "cancellation_supported": True,
            "failure_evidence_required": True,
        },
        "phases": [
            {"name": "validate", "purpose": "Validate schedule or condition, permissions, resources, and dependency availability."},
            {"name": "snapshot", "purpose": "Persist normalized task definition and checkpoint state before execution."},
            {"name": "gate", "purpose": "Apply approval and side-effect policy before external or destructive actions."},
            {"name": "execute", "purpose": "Run a bounded, idempotency-aware job with cancellation and timeout support."},
            {"name": "verify", "purpose": "Verify outputs and conditions using explicit evidence rather than model claims."},
            {"name": "recover", "purpose": "Retry eligible failures with bounded backoff or persist terminal failure evidence."},
            {"name": "record", "purpose": "Store run history, timestamps, outputs, evidence, errors, and next execution state."},
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def evaluate_automation_run_v7(run: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(run or {})
    status = str(payload.get("status") or "").strip().lower()
    evidence = payload.get("evidence")
    started = bool(payload.get("started_at"))
    finished = bool(payload.get("finished_at"))
    persisted = bool(payload.get("persisted"))
    cancelled = status == "cancelled"
    success = status == "success"
    terminal_failure = status in {"failed", "cancelled", "timed_out"}

    passed = bool(success and started and finished and persisted and evidence)
    failure_recorded = bool(terminal_failure and started and finished and persisted and evidence)

    return {
        "ok": True,
        "ready": passed,
        "status": status,
        "cancelled": cancelled,
        "failure_recorded": failure_recorded,
        "checks": {
            "started": started,
            "finished": finished,
            "persisted": persisted,
            "evidence_present": bool(evidence),
            "successful_terminal_state": success,
        },
        "policy": "Automation success requires persisted start/finish state plus explicit verification evidence; failures must remain visible and auditable.",
    }


def plan_automation_v9(
    name: str,
    objective: str,
    mode: str = "recurring",
    schedule: str = "",
    condition: str = "",
    steps: list[dict[str, Any]] | None = None,
    max_retries: int = 3,
    retry_backoff_seconds: int = 60,
    max_backoff_seconds: int = 3600,
    max_runtime_seconds: int = 900,
    overlap_policy: str = "skip",
) -> dict[str, Any]:
    try:
        normalized_mode = AutomationMode(str(mode or "recurring").strip().lower())
        normalized_overlap = OverlapPolicy(str(overlap_policy or "skip").strip().lower())
        workflow_steps: list[WorkflowStep] = []
        for index, raw in enumerate(steps or [], start=1):
            item = dict(raw or {})
            workflow_steps.append(
                WorkflowStep(
                    step_id=str(item.get("step_id") or f"step-{index}").strip(),
                    title=str(item.get("title") or item.get("action") or f"Step {index}").strip(),
                    action=str(item.get("action") or "").strip(),
                    depends_on=[str(dep).strip() for dep in item.get("depends_on") or [] if str(dep).strip()],
                    destructive=bool(item.get("destructive", False)),
                    approval_required=bool(item.get("approval_required", False)),
                )
            )
        definition = AutomationDefinition(
            name=str(name or "").strip(),
            objective=str(objective or "").strip(),
            mode=normalized_mode,
            schedule=str(schedule or "").strip(),
            condition=str(condition or "").strip(),
            overlap_policy=normalized_overlap,
            retry_policy=RetryPolicy(max_retries, retry_backoff_seconds, max_backoff_seconds),
            max_runtime_seconds=max_runtime_seconds,
            steps=workflow_steps,
        )
        result = _V9_RUNTIME.normalize_definition(definition)
        result["engine"] = "dpn-automation-workflow-v9"
        result["persistent_scheduler_compatibility"] = {
            "legacy_interval_daily_engine_preserved": True,
            "condition_execution_requires_condition_provider": normalized_mode == AutomationMode.CONDITION,
            "unsupported_runtime_paths_fail_closed": True,
        }
        return result
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "engine": "dpn-automation-workflow-v9"}


def evaluate_workflow_v9(steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    workflow_steps: list[WorkflowStep] = []
    for index, raw in enumerate(steps or [], start=1):
        item = dict(raw or {})
        try:
            status = WorkflowStepStatus(str(item.get("status") or "pending").strip().lower())
        except ValueError:
            return {"ok": False, "error": f"invalid status for step {index}"}
        workflow_steps.append(
            WorkflowStep(
                step_id=str(item.get("step_id") or f"step-{index}").strip(),
                title=str(item.get("title") or f"Step {index}").strip(),
                action=str(item.get("action") or "").strip(),
                depends_on=[str(dep).strip() for dep in item.get("depends_on") or [] if str(dep).strip()],
                status=status,
                attempts=max(0, int(item.get("attempts") or 0)),
                evidence=[str(value) for value in item.get("evidence") or [] if str(value).strip()],
                error=str(item.get("error")) if item.get("error") is not None else None,
            )
        )
    return _V9_RUNTIME.completion_summary(workflow_steps)


def register(registry):
    registry.register(
        name="plan_automation_v7",
        description="Plan a bounded one-time, recurring, or condition-driven automation with retries, backoff, overlap policy, approvals, checkpoints, and restart recovery.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["once", "recurring", "condition"], "default": "recurring"},
                "schedule": {"type": "string", "default": ""},
                "condition": {"type": "string", "default": ""},
                "max_retries": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
                "retry_backoff_seconds": {"type": "integer", "minimum": 5, "maximum": 86400, "default": 60},
                "max_runtime_seconds": {"type": "integer", "minimum": 30, "maximum": 86400, "default": 900},
                "overlap_policy": {"type": "string", "enum": ["skip", "queue", "replace"], "default": "skip"},
                "approval_required": {"type": "boolean", "default": True}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=plan_automation_v7,
        risk="read",
    )
    registry.register(
        name="evaluate_automation_run_v7",
        description="Evaluate whether an automation run has a persisted terminal state and explicit verification evidence before reporting success.",
        parameters={
            "type": "object",
            "properties": {"run": {"type": "object", "default": {}}},
            "additionalProperties": False
        },
        function=evaluate_automation_run_v7,
        risk="read",
    )
    registry.register(
        name="plan_automation_v9",
        description="Normalize a v9 one-time, recurring, or condition-driven automation with chained steps, bounded retries, overlap policy, and approval escalation.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["once", "recurring", "condition"], "default": "recurring"},
                "schedule": {"type": "string", "default": ""},
                "condition": {"type": "string", "default": ""},
                "steps": {"type": "array", "items": {"type": "object"}, "default": []},
                "max_retries": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
                "retry_backoff_seconds": {"type": "integer", "minimum": 5, "maximum": 86400, "default": 60},
                "max_backoff_seconds": {"type": "integer", "minimum": 5, "maximum": 86400, "default": 3600},
                "max_runtime_seconds": {"type": "integer", "minimum": 30, "maximum": 86400, "default": 900},
                "overlap_policy": {"type": "string", "enum": ["skip", "queue", "replace"], "default": "skip"}
            },
            "required": ["name", "objective"],
            "additionalProperties": False
        },
        function=plan_automation_v9,
        risk="read",
    )
    registry.register(
        name="evaluate_workflow_v9",
        description="Evaluate terminal workflow state and evidence across v9 automation steps before reporting completion.",
        parameters={
            "type": "object",
            "properties": {"steps": {"type": "array", "items": {"type": "object"}, "default": []}},
            "additionalProperties": False
        },
        function=evaluate_workflow_v9,
        risk="read",
    )
