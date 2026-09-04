from __future__ import annotations

from typing import Any


_MODES = {"schedule", "chain", "condition", "operations", "recovery", "audit"}
_TRIGGER_TYPES = {"manual", "interval", "daily", "event", "condition"}


def build_automation_operations_plan(
    objective: str,
    mode: str = "operations",
    trigger_type: str = "manual",
    steps: list[dict[str, Any]] | None = None,
    max_steps: int = 50,
    max_retries: int = 3,
    require_approval_for_external_actions: bool = True,
) -> dict[str, Any]:
    mode = mode if mode in _MODES else "operations"
    trigger_type = trigger_type if trigger_type in _TRIGGER_TYPES else "manual"
    max_steps = max(1, min(int(max_steps), 100))
    max_retries = max(0, min(int(max_retries), 5))
    requested_steps = (steps or [])[:max_steps]

    phases = [
        {"id": "define", "goal": "Define objective, inputs, outputs, trigger, dependencies, and acceptance criteria."},
        {"id": "permissions", "goal": "Resolve live permissions and approval boundaries immediately before execution."},
        {"id": "compose", "goal": "Build a deterministic step graph with explicit dependencies and failure semantics."},
        {"id": "validate", "goal": "Validate referenced tools, schedules, conditions, templates, and workspace paths."},
        {"id": "execute", "goal": "Execute only enabled steps whose dependencies and live permissions are satisfied."},
        {"id": "recover", "goal": "Resume from the last verified step after interruption; retry only observed transient failures."},
        {"id": "audit", "goal": "Persist execution evidence, outputs, failures, blocked actions, and the next scheduled state."},
    ]

    return {
        "ok": True,
        "objective": str(objective).strip(),
        "mode": mode,
        "trigger_type": trigger_type,
        "requested_steps": requested_steps,
        "limits": {"max_steps": max_steps, "max_retries": max_retries},
        "quality_gates": [
            "trigger_valid",
            "dependencies_acyclic",
            "referenced_tools_exist",
            "live_permissions_checked",
            "approval_requirements_preserved",
            "step_outputs_recorded",
            "completion_evidence_present",
        ],
        "execution_policy": {
            "persisted_payloads_are_not_authorization": True,
            "live_permission_check_before_every_external_action": True,
            "external_actions_require_approval": bool(require_approval_for_external_actions),
            "operator_cancellation_must_be_preserved": True,
            "application_shutdown_is_pause_not_success": True,
            "resume_from_verified_checkpoint": True,
            "do_not_repeat_verified_steps_without_reason": True,
            "do_not_retry_permission_or_validation_failures_blindly": True,
            "retry_only_observed_transient_failures": True,
            "bounded_retries": True,
            "no_recursive_unbounded_workflow_creation": True,
            "workspace_boundary_required": True,
            "audit_every_state_transition": True,
        },
        "failure_classes": {
            "transient": ["timeout", "temporary_service_unavailable", "rate_limit", "recoverable_transport"],
            "blocked": ["approval_required", "permission_revoked", "missing_credential", "disabled_capability"],
            "validation": ["invalid_schedule", "missing_tool", "invalid_template", "dependency_cycle", "invalid_path"],
            "terminal": ["operator_cancelled", "explicit_stop_condition", "unrecoverable_input"],
        },
        "phases": phases,
    }


def register(registry) -> None:
    registry.register(
        name="plan_automation_operations",
        description="Plan safe scheduled, conditional, chained, recoverable, and auditable DPN AI automation operations.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "mode": {"type": "string", "default": "operations"},
                "trigger_type": {"type": "string", "default": "manual"},
                "steps": {"type": "array", "items": {"type": "object"}},
                "max_steps": {"type": "integer", "default": 50},
                "max_retries": {"type": "integer", "default": 3},
                "require_approval_for_external_actions": {"type": "boolean", "default": True},
            },
            "required": ["objective"],
        },
        function=build_automation_operations_plan,
        risk="read",
    )
