from __future__ import annotations

from typing import Any

_MEMORY_CLASSES = {
    "decision", "fact", "preference", "artifact", "repository", "procedure", "constraint", "event", "hypothesis"
}
_RETENTION = {"session", "project", "durable", "ephemeral"}
_SOURCE_TIERS = {"primary": 1.0, "verified": 0.9, "observed": 0.85, "user": 0.8, "inferred": 0.55, "unknown": 0.4}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(float(value), maximum))


def score_memory_candidate(
    confidence: float = 0.8,
    source_tier: str = "user",
    corroborating_sources: int = 0,
    contradicted: bool = False,
    stale: bool = False,
) -> dict[str, Any]:
    source_tier = str(source_tier or "unknown").strip().lower()
    if source_tier not in _SOURCE_TIERS:
        source_tier = "unknown"
    score = _clamp(confidence) * 0.55 + _SOURCE_TIERS[source_tier] * 0.35
    score += min(max(int(corroborating_sources), 0), 5) * 0.02
    if contradicted:
        score -= 0.30
    if stale:
        score -= 0.20
    score = _clamp(score)
    if contradicted:
        disposition = "quarantine"
    elif score >= 0.82:
        disposition = "durable_candidate"
    elif score >= 0.60:
        disposition = "project_candidate"
    else:
        disposition = "ephemeral_or_review"
    return {
        "ok": True,
        "score": round(score, 3),
        "source_tier": source_tier,
        "disposition": disposition,
        "requires_review": bool(contradicted or stale or score < 0.60),
    }


def build_persistent_memory_plan(
    objective: str,
    project_id: str | None = None,
    memory_classes: list[str] | None = None,
    retention: str = "project",
    include_repository_graph: bool = True,
    include_artifact_history: bool = True,
    require_provenance: bool = True,
    allow_forgetting: bool = True,
    max_recall_items: int = 60,
) -> dict[str, Any]:
    requested = []
    for item in memory_classes or ["decision", "fact", "artifact", "repository", "constraint"]:
        value = str(item or "").strip().lower()
        if value in _MEMORY_CLASSES and value not in requested:
            requested.append(value)
    if not requested:
        requested = ["fact"]
    retention = str(retention or "project").strip().lower()
    if retention not in _RETENTION:
        retention = "project"
    max_recall_items = max(5, min(int(max_recall_items), 200))

    stages = [
        {"name": "scope", "purpose": "Resolve project/session scope, memory classes, retention policy, and privacy boundary before storing or recalling anything."},
        {"name": "recall", "purpose": "Retrieve a bounded set of relevant semantic memories, graph nodes/edges, decisions, repository facts, and artifact history.", "max_items": max_recall_items},
        {"name": "rank", "purpose": "Rank recalled items by relevance, provenance quality, confidence, recency, project match, and contradiction state instead of raw similarity alone."},
        {"name": "reconcile", "purpose": "Keep competing facts visible, identify superseded decisions, distinguish historical truth from current truth, and lower confidence when evidence conflicts."},
        {"name": "execute", "purpose": "Use only memory that remains relevant and sufficiently supported; refresh current facts from authoritative sources when freshness matters."},
        {"name": "capture", "purpose": "Extract new durable candidates such as explicit decisions, constraints, verified facts, repository relationships, artifact lineage, and procedures."},
        {"name": "validate", "purpose": "Require source/provenance, project scope, confidence, timestamps, and evidence links before promoting important memory."},
        {"name": "graph_update", "purpose": "Connect people/projects/repos/files/artifacts/decisions/events/components using provenance-aware nodes and edges; mark inferred edges as inferred."},
        {"name": "maintenance", "purpose": "Refresh stale memories, mark superseded items, merge true duplicates without erasing provenance, and quarantine contradictions."},
        {"name": "deliver", "purpose": "Report which memory materially affected the result, what was refreshed, what remains uncertain, and any stale/contradictory items that were excluded."},
    ]

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "project_id": project_id,
        "memory_classes": requested,
        "retention": retention,
        "features": {
            "semantic_memory": True,
            "knowledge_graph": True,
            "decision_history": "decision" in requested,
            "repository_graph": bool(include_repository_graph),
            "artifact_history": bool(include_artifact_history),
            "contradiction_tracking": True,
            "supersession_tracking": True,
            "confidence_scoring": True,
            "source_provenance": bool(require_provenance),
            "controlled_forgetting": bool(allow_forgetting),
        },
        "quality_gates": [
            "project_scope_known", "source_provenance_recorded", "confidence_recorded",
            "contradictions_not_silently_overwritten", "stale_current_facts_refreshed",
            "historical_and_current_state_distinguished", "memory_use_disclosed_when_material",
        ],
        "execution_policy": {
            "do_not_treat_memory_as_ground_truth": True,
            "do_not_overwrite_conflicting_memory_silently": True,
            "do_not_promote_inference_to_fact_without_evidence": True,
            "prefer_project_scoped_memory_over_global_when_relevant": True,
            "preserve_provenance_when_merging_duplicates": True,
            "refresh_time_sensitive_facts_before_use": True,
            "forgetting_requires_explicit_scope_and_reason": bool(allow_forgetting),
            "never_store_secrets_in_plaintext_memory": True,
            "bounded_recall_required": True,
        },
        "maintenance_policy": {
            "stale_action": "refresh_or_demote",
            "contradiction_action": "quarantine_and_compare_sources",
            "superseded_action": "retain_history_mark_inactive",
            "duplicate_action": "link_or_merge_without_losing_sources",
            "low_confidence_action": "keep_ephemeral_or_request_review",
        },
        "stages": stages,
    }


def register(registry):
    registry.register(
        name="plan_persistent_memory",
        description="Plan project-scoped long-term memory, semantic recall, provenance-aware knowledge graphs, decision history, contradiction handling, refresh, and controlled forgetting.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "project_id": {"type": ["string", "null"], "default": None},
                "memory_classes": {"type": "array", "items": {"type": "string"}, "default": []},
                "retention": {"type": "string", "enum": ["session", "project", "durable", "ephemeral"], "default": "project"},
                "include_repository_graph": {"type": "boolean", "default": True},
                "include_artifact_history": {"type": "boolean", "default": True},
                "require_provenance": {"type": "boolean", "default": True},
                "allow_forgetting": {"type": "boolean", "default": True},
                "max_recall_items": {"type": "integer", "minimum": 5, "maximum": 200, "default": 60}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_persistent_memory_plan,
        risk="read",
    )
    registry.register(
        name="score_memory_candidate",
        description="Score whether a candidate memory should remain ephemeral, become project memory, become durable memory, or be quarantined for contradiction review.",
        parameters={
            "type": "object",
            "properties": {
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
                "source_tier": {"type": "string", "enum": ["primary", "verified", "observed", "user", "inferred", "unknown"], "default": "user"},
                "corroborating_sources": {"type": "integer", "minimum": 0, "maximum": 100, "default": 0},
                "contradicted": {"type": "boolean", "default": False},
                "stale": {"type": "boolean", "default": False}
            },
            "additionalProperties": False
        },
        function=score_memory_candidate,
        risk="read",
    )
