from __future__ import annotations

from typing import Any

ARTIFACT_TYPES = {"code", "document", "pdf", "spreadsheet", "presentation", "image", "research", "automation", "connector", "project", "generic"}
SEVERITIES = {"info", "warning", "error", "critical"}


def build_self_verification_plan(
    objective: str,
    artifact_type: str = "generic",
    require_independent_check: bool = True,
    max_repair_attempts: int = 2,
) -> dict[str, Any]:
    artifact_type = str(artifact_type or "generic").strip().lower()
    if artifact_type not in ARTIFACT_TYPES:
        artifact_type = "generic"
    repair_cap = max(0, min(int(max_repair_attempts), 4))
    validators = {
        "code": ["targeted_tests", "regression_tests", "diff_review", "security_checks", "runtime_or_build_evidence"],
        "document": ["artifact_exists", "format_validation", "content_requirements", "visual_or_structural_review"],
        "pdf": ["artifact_exists", "render_validation", "page_integrity", "content_requirements"],
        "spreadsheet": ["artifact_exists", "formula_or_data_validation", "sheet_structure", "content_requirements"],
        "presentation": ["artifact_exists", "slide_structure", "content_requirements", "visual_review"],
        "image": ["artifact_exists", "decode_validation", "visual_review", "requested_attributes"],
        "research": ["source_presence", "claim_support", "citation_integrity", "freshness_or_date_check", "contradiction_review"],
        "automation": ["persisted_run_state", "terminal_status", "execution_evidence", "side_effect_readback_if_applicable"],
        "connector": ["authorization", "schema_match", "target_resolution", "response_validation", "write_readback_if_applicable"],
        "project": ["current_state_refresh", "provenance", "reconciliation", "verification"],
        "generic": ["output_exists", "requirements_match", "evidence_present"],
    }[artifact_type]
    return {
        "ok": bool(str(objective or "").strip()),
        "objective": str(objective or "").strip(),
        "artifact_type": artifact_type,
        "limits": {"max_repair_attempts": repair_cap},
        "validators": validators,
        "stages": [
            {"id": "contract", "goal": "Convert the requested outcome into explicit verifiable acceptance criteria before judging success."},
            {"id": "collect", "goal": "Collect direct evidence from tests, artifacts, responses, logs, repository state, citations, or readback depending on the task."},
            {"id": "verify", "goal": "Check each acceptance criterion against direct evidence rather than the producing agent's claim."},
            {"id": "challenge", "goal": "Look for counter-evidence, contradictions, missing requirements, stale facts, partial failure, and unsupported assumptions."},
            {"id": "independent_review", "goal": "When required and available, use a separate verifier/critic path or distinct validation method instead of self-attestation alone."},
            {"id": "repair", "goal": "Repair only safe code/content defects within the bounded attempt budget; never weaken tests, security controls, or acceptance criteria."},
            {"id": "reverify", "goal": "Re-run affected validations after every repair and invalidate stale evidence from before the change."},
            {"id": "decision", "goal": "Return pass, partial, blocked, or fail with evidence, residual risk, and unresolved items. Never convert unknown into success."},
        ],
        "quality_gates": [
            "acceptance_criteria_explicit", "direct_evidence_collected", "all_required_validators_run_or_disclosed_unavailable",
            "counter_evidence_considered", "repairs_reverified", "stale_evidence_invalidated",
            "critical_failures_block_success", "missing_evidence_blocks_success", "residual_risk_reported"
        ],
        "execution_policy": {
            "independent_check_required": bool(require_independent_check),
            "producer_claim_is_not_verification": True,
            "tests_must_not_be_weakened_to_pass": True,
            "security_controls_must_not_be_disabled": True,
            "acceptance_criteria_must_not_be_relaxed_after_failure": True,
            "missing_tool_or_evidence_must_be_disclosed": True,
            "partial_success_must_not_be_reported_as_full_success": True,
            "critical_or_security_failure_blocks_completion": True,
            "repair_attempts_bounded": True,
            "reverify_after_every_repair": True,
            "evidence_must_identify_source_and_time_or_revision_when_material": True,
        },
    }


def evaluate_verification_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    criteria = list(evidence.get("criteria") or [])
    checks = list(evidence.get("checks") or [])
    blockers = list(evidence.get("blockers") or [])
    unresolved = list(evidence.get("unresolved") or [])
    missing = []
    if not criteria:
        missing.append("criteria")
    if not checks:
        missing.append("checks")
    failed_checks = [c for c in checks if str(c.get("status", "")).lower() in {"fail", "failed", "error", "critical"}]
    unsupported = [c for c in checks if not c.get("evidence")]
    complete = not missing and not blockers and not failed_checks and not unsupported
    if complete and unresolved:
        status = "partial"
    elif complete:
        status = "pass"
    elif blockers:
        status = "blocked"
    else:
        status = "fail"
    return {
        "ok": complete and not unresolved,
        "status": status,
        "missing_evidence": missing,
        "failed_checks": failed_checks,
        "unsupported_checks": unsupported,
        "blockers": blockers,
        "unresolved": unresolved,
        "completion_allowed": complete and not unresolved,
        "policy": {
            "unknown_is_not_success": True,
            "failed_check_blocks_completion": bool(failed_checks),
            "unsupported_check_blocks_completion": bool(unsupported),
            "unresolved_items_prevent_full_success": bool(unresolved),
        },
    }


def register(registry) -> None:
    registry.register(
        name="plan_self_verification_v7",
        description="Plan evidence-driven self-verification with explicit acceptance criteria, independent checking, bounded repair, re-verification, and strict completion gates.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "artifact_type": {"type": "string", "default": "generic"},
                "require_independent_check": {"type": "boolean", "default": True},
                "max_repair_attempts": {"type": "integer", "default": 2}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_self_verification_plan,
        risk="read"
    )
    registry.register(
        name="evaluate_verification_evidence_v7",
        description="Evaluate acceptance criteria and evidence and block completion on failed, unsupported, blocked, or unresolved checks.",
        parameters={"type": "object", "properties": {"evidence": {"type": "object"}}, "required": ["evidence"]},
        function=evaluate_verification_evidence,
        risk="read"
    )
