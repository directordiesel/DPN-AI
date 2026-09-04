from __future__ import annotations

from typing import Any


_TASK_PROFILES = {
    "general": {"profile": "auto", "vision": False, "review": False, "priority": "balanced"},
    "coding": {"profile": "software", "vision": False, "review": True, "priority": "quality"},
    "research": {"profile": "research", "vision": False, "review": True, "priority": "quality"},
    "documents": {"profile": "documents", "vision": False, "review": True, "priority": "balanced"},
    "vision": {"profile": "media", "vision": True, "review": True, "priority": "quality"},
    "data": {"profile": "data", "vision": False, "review": True, "priority": "quality"},
    "automation": {"profile": "automation", "vision": False, "review": True, "priority": "balanced"},
    "repository": {"profile": "software", "vision": False, "review": True, "priority": "quality"},
}

_ALIASES = {
    "code": "coding", "software": "coding", "debug": "coding", "repo": "repository",
    "github": "repository", "image": "vision", "photo": "vision", "pdf": "documents",
    "docx": "documents", "xlsx": "data", "spreadsheet": "data", "web": "research",
}


def _normalize_tasks(tasks: list[str] | None) -> list[str]:
    output: list[str] = []
    for item in tasks or ["general"]:
        value = str(item).strip().lower()
        value = _ALIASES.get(value, value)
        if value in _TASK_PROFILES and value not in output:
            output.append(value)
    return output or ["general"]


def build_model_routing_plan(
    objective: str,
    task_types: list[str] | None = None,
    intelligence_mode: str = "maximum",
    latency_preference: str = "balanced",
    cost_preference: str = "balanced",
    require_independent_review: bool = True,
    allow_external_models: bool = False,
) -> dict[str, Any]:
    tasks = _normalize_tasks(task_types)
    intelligence_mode = str(intelligence_mode or "maximum").lower()
    if intelligence_mode not in {"maximum", "balanced", "fast", "manual"}:
        intelligence_mode = "maximum"
    latency_preference = str(latency_preference or "balanced").lower()
    if latency_preference not in {"low", "balanced", "quality"}:
        latency_preference = "balanced"
    cost_preference = str(cost_preference or "balanced").lower()
    if cost_preference not in {"low", "balanced", "quality"}:
        cost_preference = "balanced"

    require_vision = any(_TASK_PROFILES[item]["vision"] for item in tasks)
    reviewer_needed = bool(require_independent_review and any(_TASK_PROFILES[item]["review"] for item in tasks))
    profiles = list(dict.fromkeys(_TASK_PROFILES[item]["profile"] for item in tasks))

    stages = [
        {"name": "classify", "purpose": "Determine task types, required capabilities, context size, vision requirements, tool needs, and expected output."},
        {"name": "discover_models", "purpose": "Inspect actually available model providers and capabilities before selecting a model."},
        {"name": "rank", "purpose": "Rank compatible models by task fit, vision capability, reasoning/code affinity, latency preference, and configured provider policy."},
        {"name": "execute", "purpose": "Run the primary specialist with the selected model and record the actual provider/model used."},
    ]
    if reviewer_needed:
        stages.append({"name": "review", "purpose": "Use an independent reviewer pass when possible; compare against acceptance criteria and observed tool evidence."})
    stages.extend([
        {"name": "fallback", "purpose": "If the chosen model is unavailable or fails, select the next compatible model and disclose the fallback rather than silently changing capability."},
        {"name": "deliver", "purpose": "Return model/provider routing evidence, reviewer outcome, fallback history, validation evidence, and limitations."},
    ])

    return {
        "ok": True,
        "objective": objective.strip(),
        "task_types": tasks,
        "model_profiles": profiles,
        "require_vision": require_vision,
        "intelligence_mode": intelligence_mode,
        "latency_preference": latency_preference,
        "cost_preference": cost_preference,
        "independent_review_required": reviewer_needed,
        "allow_external_models": bool(allow_external_models),
        "routing_policy": {
            "discover_before_select": True,
            "prefer_local_by_default": not bool(allow_external_models),
            "external_requires_explicit_enablement": True,
            "record_actual_model_and_provider": True,
            "do_not_claim_model_capability_without_observed_availability": True,
            "do_not_silently_downgrade_vision_or_tool_requirements": True,
            "fallbacks_must_be_disclosed": True,
            "reviewer_should_differ_from_primary_when_practical": reviewer_needed,
            "review_must_use_acceptance_criteria_and_tool_evidence": reviewer_needed,
            "manual_mode_preserves_user_model_choice": intelligence_mode == "manual",
        },
        "quality_gates": [
            "selected_model_available",
            "required_modalities_supported",
            "actual_model_recorded",
            "fallback_history_recorded",
            "review_completed_if_required",
            "completion_claims_match_tool_evidence",
        ],
        "stages": stages,
    }


def register(registry):
    registry.register(
        name="plan_intelligent_model_routing",
        description="Plan task-aware model and specialist routing with model discovery, vision requirements, reviewer passes, explicit fallbacks, and evidence of the actual provider/model used.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "task_types": {"type": "array", "items": {"type": "string"}, "default": ["general"]},
                "intelligence_mode": {"type": "string", "enum": ["maximum", "balanced", "fast", "manual"], "default": "maximum"},
                "latency_preference": {"type": "string", "enum": ["low", "balanced", "quality"], "default": "balanced"},
                "cost_preference": {"type": "string", "enum": ["low", "balanced", "quality"], "default": "balanced"},
                "require_independent_review": {"type": "boolean", "default": True},
                "allow_external_models": {"type": "boolean", "default": False}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_model_routing_plan,
        risk="read",
    )
