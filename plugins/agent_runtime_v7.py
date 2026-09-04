from __future__ import annotations

from typing import Any

_AGENT_ROLES = {
    "planner",
    "coder",
    "researcher",
    "creator",
    "automation",
    "critic",
    "verifier",
}

_STEP_STATES = {"pending", "ready", "running", "blocked", "failed", "complete", "cancelled"}


def _clean_strings(values: list[str] | None, limit: int) -> list[str]:
    return [str(item).strip() for item in (values or []) if str(item).strip()][:limit]


def build_agent_mission(
    objective: str,
    acceptance_criteria: list[str] | None = None,
    requested_capabilities: list[str] | None = None,
    max_steps: int = 12,
    max_repair_passes: int = 3,
    require_verification: bool = True,
) -> dict[str, Any]:
    objective = str(objective or "").strip()
    if not objective:
        return {"ok": False, "error": "objective is required"}

    criteria = _clean_strings(acceptance_criteria, 50)
    capabilities = _clean_strings(requested_capabilities, 50)
    step_budget = max(1, min(int(max_steps), 32))
    repair_budget = max(0, min(int(max_repair_passes), 5))

    stages: list[dict[str, Any]] = [
        {
            "name": "understand",
            "agent": "planner",
            "purpose": "Translate the objective into explicit constraints, risks, dependencies, and measurable acceptance criteria.",
        },
        {
            "name": "inspect_context",
            "agent": "planner",
            "purpose": "Inspect repository/project state and gather evidence before deciding what must change.",
        },
        {
            "name": "plan",
            "agent": "planner",
            "purpose": "Produce the smallest dependency-aware execution graph that can satisfy the objective within the step budget.",
        },
        {
            "name": "execute",
            "agent": "coder",
            "purpose": "Delegate bounded work to the appropriate specialist agents while preserving tool, permission, and workspace policies.",
        },
        {
            "name": "critique",
            "agent": "critic",
            "purpose": "Challenge assumptions, inspect generated work for defects, and identify missing evidence without silently broadening scope.",
        },
    ]
    if require_verification:
        stages.append(
            {
                "name": "verify",
                "agent": "verifier",
                "purpose": "Run objective-specific checks and require observable evidence before completion can be claimed.",
            }
        )
    if repair_budget:
        stages.append(
            {
                "name": "repair",
                "agent": "coder",
                "purpose": "Apply only evidence-supported repairs, then return to verification.",
                "max_passes": repair_budget,
            }
        )
    stages.append(
        {
            "name": "checkpoint",
            "agent": "planner",
            "purpose": "Persist mission state, evidence, artifacts, remaining work, and the next safe resume point.",
        }
    )

    return {
        "ok": True,
        "runtime": "dpn-agent-runtime-v7",
        "objective": objective,
        "acceptance_criteria": criteria,
        "requested_capabilities": capabilities,
        "step_budget": step_budget,
        "repair_budget": repair_budget,
        "require_verification": bool(require_verification),
        "agent_roles": sorted(_AGENT_ROLES),
        "step_states": sorted(_STEP_STATES),
        "execution_policy": {
            "evidence_before_action": True,
            "plan_before_write": True,
            "least_privilege_tools": True,
            "approval_boundaries_preserved": True,
            "workspace_confinement_preserved": True,
            "no_implicit_dependency_installs": True,
            "no_destructive_actions_without_authorization": True,
            "bounded_steps": True,
            "bounded_repairs": True,
            "operator_cancellation_is_terminal": True,
            "application_shutdown_is_resumable_pause": True,
            "completion_requires_verification": bool(require_verification),
            "record_tool_and_model_evidence": True,
        },
        "stages": stages,
    }


def route_agent_role(task: str, capabilities: list[str] | None = None) -> dict[str, Any]:
    text = f"{task} {' '.join(capabilities or [])}".lower()
    if any(token in text for token in ("test", "verify", "validate", "qa", "security", "audit")):
        role = "verifier"
    elif any(token in text for token in ("review", "critique", "inspect", "risk")):
        role = "critic"
    elif any(token in text for token in ("schedule", "automation", "workflow", "recurring", "trigger")):
        role = "automation"
    elif any(token in text for token in ("image", "document", "pdf", "spreadsheet", "presentation", "artifact")):
        role = "creator"
    elif any(token in text for token in ("research", "browser", "source", "web")):
        role = "researcher"
    elif any(token in text for token in ("code", "bug", "repo", "repository", "build", "implement", "refactor")):
        role = "coder"
    else:
        role = "planner"
    return {"ok": True, "role": role, "task": str(task or "").strip()}


def evaluate_agent_step(
    state: str,
    evidence: list[str] | None = None,
    error: str | None = None,
    approval_required: bool = False,
    approval_granted: bool = False,
) -> dict[str, Any]:
    state = str(state or "pending").strip().lower()
    if state not in _STEP_STATES:
        state = "pending"
    evidence_items = _clean_strings(evidence, 100)

    if approval_required and not approval_granted and state in {"ready", "running", "complete"}:
        effective_state = "blocked"
        reason = "approval_required"
    elif state == "complete" and not evidence_items:
        effective_state = "blocked"
        reason = "completion_requires_evidence"
    elif state == "failed" and not str(error or "").strip():
        effective_state = "failed"
        reason = "failure_without_error_detail"
    else:
        effective_state = state
        reason = None

    return {
        "ok": True,
        "requested_state": state,
        "state": effective_state,
        "evidence": evidence_items,
        "error": str(error or "").strip() or None,
        "approval_required": bool(approval_required),
        "approval_granted": bool(approval_granted),
        "reason": reason,
    }


def register(registry):
    registry.register(
        name="build_agent_mission_v7",
        description="Build a bounded, evidence-driven multi-agent mission plan for DPN AI v7.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}, "default": []},
                "requested_capabilities": {"type": "array", "items": {"type": "string"}, "default": []},
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 32, "default": 12},
                "max_repair_passes": {"type": "integer", "minimum": 0, "maximum": 5, "default": 3},
                "require_verification": {"type": "boolean", "default": True}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_agent_mission,
        risk="read",
    )
    registry.register(
        name="route_agent_role_v7",
        description="Route a mission step to a bounded specialist role without granting extra permissions.",
        parameters={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "capabilities": {"type": "array", "items": {"type": "string"}, "default": []}
            },
            "required": ["task"],
            "additionalProperties": False
        },
        function=route_agent_role,
        risk="read",
    )
    registry.register(
        name="evaluate_agent_step_v7",
        description="Evaluate agent step state while enforcing evidence and approval boundaries.",
        parameters={
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": sorted(_STEP_STATES)},
                "evidence": {"type": "array", "items": {"type": "string"}, "default": []},
                "error": {"type": ["string", "null"]},
                "approval_required": {"type": "boolean", "default": False},
                "approval_granted": {"type": "boolean", "default": False}
            },
            "required": ["state"],
            "additionalProperties": False
        },
        function=evaluate_agent_step,
        risk="read",
    )
