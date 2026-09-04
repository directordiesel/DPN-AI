from __future__ import annotations

from typing import Any

PROJECT_DOMAINS = {
    "architecture", "repository", "decision", "requirement", "artifact", "issue",
    "test", "release", "dependency", "automation", "security", "performance", "history"
}


def build_project_intelligence_plan(
    objective: str,
    project_id: str,
    domains: list[str] | None = None,
    max_recall_items: int = 80,
    require_fresh_repository_state: bool = True,
) -> dict[str, Any]:
    selected: list[str] = []
    for item in domains or ["architecture", "repository", "decision", "issue", "test", "release"]:
        value = str(item or "").strip().lower()
        if value in PROJECT_DOMAINS and value not in selected:
            selected.append(value)
    if not selected:
        selected = ["repository"]
    recall_cap = max(10, min(int(max_recall_items), 250))
    return {
        "ok": bool(str(objective or "").strip() and str(project_id or "").strip()),
        "objective": str(objective or "").strip(),
        "project_id": str(project_id or "").strip(),
        "domains": selected,
        "limits": {"max_recall_items": recall_cap},
        "stages": [
            {"id": "scope", "goal": "Resolve the exact project, repository/workspace, active branch/release context, and privacy boundary."},
            {"id": "inventory", "goal": "Inventory current files, components, dependencies, tests, releases, open work, decisions, artifacts, and known risks."},
            {"id": "recall", "goal": "Recall bounded project-scoped history with provenance, confidence, timestamps, and supersession state."},
            {"id": "refresh", "goal": "Refresh repository, CI, issue, release, dependency, or runtime facts from authoritative current state when they can change."},
            {"id": "graph", "goal": "Build or update provenance-aware relationships among files, symbols, components, decisions, requirements, issues, tests, artifacts, and releases."},
            {"id": "reconcile", "goal": "Reconcile stale, contradictory, duplicated, renamed, deleted, or superseded project knowledge without erasing history."},
            {"id": "reason", "goal": "Use current evidence plus relevant project history to determine impact, dependencies, next work, and constraints."},
            {"id": "capture", "goal": "Capture verified new decisions, architecture changes, fixes, tests, artifacts, release state, and unresolved risks with evidence."},
            {"id": "verify", "goal": "Verify important project-state claims against repository/test/artifact evidence before persistence or completion claims."},
            {"id": "deliver", "goal": "Report current state, material recalled context, refreshed facts, unresolved contradictions, and concrete next actions."},
        ],
        "quality_gates": [
            "project_identity_known", "project_scope_preserved", "provenance_recorded",
            "confidence_recorded", "current_repository_state_refreshed", "deleted_or_renamed_items_reconciled",
            "contradictions_visible", "superseded_decisions_retained_as_history", "important_claims_verified",
            "secrets_not_persisted_plaintext",
        ],
        "execution_policy": {
            "project_memory_over_global_memory_when_relevant": True,
            "memory_is_context_not_ground_truth": True,
            "require_fresh_repository_state": bool(require_fresh_repository_state),
            "refresh_mutable_facts_before_material_use": True,
            "never_silently_overwrite_conflicts": True,
            "never_promote_inference_to_verified_fact": True,
            "preserve_decision_and_release_history": True,
            "track_file_symbol_component_lineage": True,
            "track_test_and_failure_history": True,
            "track_artifact_and_release_lineage": True,
            "record_unresolved_risks_and_blockers": True,
            "bounded_recall_required": True,
            "never_store_secrets_in_plaintext": True,
        },
    }


def evaluate_project_intelligence_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    required = [
        "project_identity", "scope", "provenance", "confidence", "current_state",
        "reconciliation", "verification"
    ]
    missing = [key for key in required if not evidence.get(key)]
    contradictions = list(evidence.get("unresolved_contradictions") or [])
    blockers = list(evidence.get("blockers") or [])
    return {
        "ok": not missing and not blockers,
        "missing_evidence": missing,
        "unresolved_contradictions": contradictions,
        "blockers": blockers,
        "completion_allowed": not missing and not blockers,
        "policy": {
            "contradictions_must_be_disclosed": bool(contradictions),
            "missing_evidence_blocks_completion": True,
            "blockers_cannot_be_reported_as_success": True,
        },
    }


def register(registry) -> None:
    registry.register(
        name="plan_project_intelligence_v7",
        description="Plan persistent project intelligence with repository refresh, provenance-aware project graphs, decision/test/release history, contradiction reconciliation, and verified persistence.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "project_id": {"type": "string", "minLength": 1},
                "domains": {"type": "array", "items": {"type": "string"}},
                "max_recall_items": {"type": "integer", "default": 80},
                "require_fresh_repository_state": {"type": "boolean", "default": True}
            },
            "required": ["objective", "project_id"],
            "additionalProperties": False
        },
        function=build_project_intelligence_plan,
        risk="read"
    )
    registry.register(
        name="evaluate_project_intelligence_evidence_v7",
        description="Evaluate whether persistent project-intelligence evidence is sufficient for a completion claim.",
        parameters={"type": "object", "properties": {"evidence": {"type": "object"}}, "required": ["evidence"]},
        function=evaluate_project_intelligence_evidence,
        risk="read"
    )
