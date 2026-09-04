from __future__ import annotations

from typing import Any

_MODES = {"resume", "recover", "evaluate", "repair", "verify"}
_FAILURES = {"validation", "tool", "dependency", "timeout", "interruption", "permission", "unknown"}


def build_mission_recovery_plan(
    objective: str,
    mode: str = "recover",
    failure_type: str = "unknown",
    acceptance_criteria: list[str] | None = None,
    checkpoint_evidence: list[str] | None = None,
    max_repair_passes: int = 3,
    allow_replan: bool = True,
) -> dict[str, Any]:
    mode = str(mode or "recover").strip().lower()
    failure_type = str(failure_type or "unknown").strip().lower()
    if mode not in _MODES:
        mode = "recover"
    if failure_type not in _FAILURES:
        failure_type = "unknown"
    criteria = [str(item).strip() for item in (acceptance_criteria or []) if str(item).strip()][:50]
    evidence = [str(item).strip() for item in (checkpoint_evidence or []) if str(item).strip()][:100]
    repairs = max(0, min(int(max_repair_passes), 5))

    stages = [
        {"name": "recover_state", "purpose": "Load mission state, last durable checkpoint, completed steps, tool evidence, artifacts, errors, and unresolved acceptance criteria."},
        {"name": "validate_checkpoint", "purpose": "Verify checkpoint evidence still exists and is internally consistent before trusting it."},
        {"name": "classify_failure", "purpose": "Classify the observed failure from actual logs/tool output; do not invent a cause.", "failure_type": failure_type},
        {"name": "self_evaluate", "purpose": "Compare current evidence against acceptance criteria and identify satisfied, failed, blocked, and unverified requirements."},
    ]
    if allow_replan:
        stages.append({"name": "replan", "purpose": "Revise only the failed or blocked portion of the plan while preserving verified completed work and safety boundaries."})
    if repairs:
        stages.append({"name": "bounded_repair", "purpose": "Apply the smallest evidence-supported repair and re-run the failed validation.", "max_passes": repairs})
    stages.extend([
        {"name": "regression_check", "purpose": "Re-run relevant validations for affected work so a local repair does not create a broader regression."},
        {"name": "completion_gate", "purpose": "Mark complete only if every required acceptance criterion has observable evidence; otherwise remain blocked, failed, or incomplete."},
        {"name": "checkpoint", "purpose": "Persist the new mission state, evidence, remaining work, actual model/tool outcomes, and next safe resume point."},
    ])

    return {
        "ok": True,
        "objective": objective.strip(),
        "mode": mode,
        "failure_type": failure_type,
        "acceptance_criteria": criteria,
        "checkpoint_evidence": evidence,
        "repair_budget": repairs,
        "allow_replan": bool(allow_replan),
        "required_capabilities": ["persistent_missions", "background_jobs", "snapshots", "validation", "audit", "memory"],
        "quality_gates": ["checkpoint_verified", "failure_evidence_present", "acceptance_criteria_evaluated", "repairs_revalidated", "completion_evidence_complete"],
        "execution_policy": {
            "resume_from_verified_checkpoint": True,
            "do_not_repeat_verified_work_unnecessarily": True,
            "do_not_guess_failure_cause": True,
            "do_not_bypass_approval_or_permission_boundaries": True,
            "do_not_install_dependencies_implicitly": True,
            "do_not_mark_complete_with_unverified_criteria": True,
            "preserve_operator_cancellation": True,
            "application_shutdown_is_pause_not_success": True,
            "bounded_retries_only": True,
            "replan_only_from_observed_evidence": True,
            "record_actual_tool_and_model_outcomes": True,
        },
        "stages": stages,
    }


def evaluate_mission_completion(criteria: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = list(criteria or [])[:100]
    normalized = []
    complete = True
    for item in items:
        name = str(item.get("criterion") or item.get("name") or "").strip()
        status = str(item.get("status") or "unverified").strip().lower()
        evidence = item.get("evidence")
        passed = status in {"passed", "satisfied", "complete"} and bool(evidence)
        normalized.append({"criterion": name, "status": status, "evidence": evidence, "passed": passed})
        if not passed:
            complete = False
    if not items:
        complete = False
    return {
        "ok": True,
        "complete": complete,
        "criteria": normalized,
        "remaining": [item["criterion"] for item in normalized if not item["passed"]],
        "policy": "Completion requires explicit evidence for every acceptance criterion.",
    }


def register(registry):
    registry.register(
        name="plan_mission_recovery",
        description="Plan evidence-driven recovery, self-evaluation, bounded repair, resume, and completion gating for interrupted or failing DPN AI missions.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": sorted(_MODES), "default": "recover"},
                "failure_type": {"type": "string", "enum": sorted(_FAILURES), "default": "unknown"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}, "default": []},
                "checkpoint_evidence": {"type": "array", "items": {"type": "string"}, "default": []},
                "max_repair_passes": {"type": "integer", "minimum": 0, "maximum": 5, "default": 3},
                "allow_replan": {"type": "boolean", "default": True}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_mission_recovery_plan,
        risk="read",
    )
    registry.register(
        name="evaluate_mission_completion",
        description="Evaluate mission acceptance criteria and refuse completion when any criterion lacks explicit passing evidence.",
        parameters={
            "type": "object",
            "properties": {"criteria": {"type": "array", "items": {"type": "object"}, "default": []}},
            "additionalProperties": False
        },
        function=evaluate_mission_completion,
        risk="read",
    )
