from __future__ import annotations

from typing import Any


_ARTIFACT_PROFILES: dict[str, dict[str, Any]] = {
    "code": {
        "specialist": "software",
        "capabilities": ["workspace", "code_execution", "testing", "release_packaging"],
        "quality_gates": ["syntax_check", "tests", "security_review", "artifact_exists"],
        "preferred_tools": ["workspace", "run_python_sandbox", "shell", "discover_tools"],
    },
    "document": {
        "specialist": "documents",
        "capabilities": ["document_generation", "workspace", "editing", "validation"],
        "quality_gates": ["artifact_exists", "opens_successfully", "required_sections_present"],
        "preferred_tools": ["document", "pdf", "spreadsheet", "presentation", "discover_tools"],
    },
    "image": {
        "specialist": "media",
        "capabilities": ["image_generation", "vision", "media_processing", "workspace"],
        "quality_gates": ["artifact_exists", "dimensions_valid", "prompt_requirements_met"],
        "preferred_tools": ["image", "media", "vision", "discover_tools"],
    },
    "research": {
        "specialist": "research",
        "capabilities": ["web_research", "source_verification", "knowledge_indexing"],
        "quality_gates": ["sources_present", "claims_supported", "freshness_checked"],
        "preferred_tools": ["web", "knowledge", "discover_tools"],
    },
    "automation": {
        "specialist": "automation",
        "capabilities": ["workflows", "scheduling", "connectors", "mcp"],
        "quality_gates": ["trigger_valid", "permissions_checked", "dry_run_or_validation"],
        "preferred_tools": ["workflow", "automation", "connector", "mcp", "discover_tools"],
    },
    "data": {
        "specialist": "data",
        "capabilities": ["python", "data_processing", "charting", "spreadsheet"],
        "quality_gates": ["input_validated", "calculation_checked", "artifact_exists"],
        "preferred_tools": ["run_python_sandbox", "spreadsheet", "discover_tools"],
    },
    "media": {
        "specialist": "media",
        "capabilities": ["audio", "video", "image", "ffmpeg", "workspace"],
        "quality_gates": ["artifact_exists", "media_probe_passes", "output_playable"],
        "preferred_tools": ["media", "image", "voice", "discover_tools"],
    },
}


def _normalize_artifacts(artifacts: list[str] | None) -> list[str]:
    aliases = {
        "app": "code",
        "software": "code",
        "program": "code",
        "website": "code",
        "script": "code",
        "pdf": "document",
        "word": "document",
        "docx": "document",
        "excel": "data",
        "xlsx": "data",
        "powerpoint": "document",
        "pptx": "document",
        "picture": "image",
        "photo": "image",
        "graphic": "image",
        "chart": "data",
        "spreadsheet": "data",
        "video": "media",
        "audio": "media",
        "voice": "media",
        "workflow": "automation",
        "schedule": "automation",
    }
    result: list[str] = []
    for raw in artifacts or []:
        key = str(raw).strip().lower()
        key = aliases.get(key, key)
        if key in _ARTIFACT_PROFILES and key not in result:
            result.append(key)
    return result or ["code", "document", "image", "research"]


def build_universal_execution_plan(
    objective: str,
    artifacts: list[str] | None = None,
    require_validation: bool = True,
    allow_external_actions: bool = False,
) -> dict[str, Any]:
    """Create a deterministic capability plan for broad multimodal DPN AI requests.

    This does not execute side effects. It gives the model/orchestrator an explicit
    map of specialists, capability families, quality gates, and tool-discovery hints.
    """
    selected = _normalize_artifacts(artifacts)
    profiles = [_ARTIFACT_PROFILES[name] for name in selected]

    capabilities = list(dict.fromkeys(cap for profile in profiles for cap in profile["capabilities"]))
    specialists = list(dict.fromkeys(profile["specialist"] for profile in profiles))
    preferred_tools = list(dict.fromkeys(tool for profile in profiles for tool in profile["preferred_tools"]))
    quality_gates = list(dict.fromkeys(gate for profile in profiles for gate in profile["quality_gates"]))
    if not require_validation:
        quality_gates = [gate for gate in quality_gates if gate not in {"tests", "security_review", "claims_supported"}]

    phases = [
        {
            "name": "understand",
            "purpose": "Turn the request into explicit deliverables, constraints, assumptions, and success criteria.",
            "specialist": "director",
        },
        {
            "name": "discover",
            "purpose": "Discover the smallest safe tool set that can produce each requested artifact.",
            "specialist": "director",
        },
        {
            "name": "build",
            "purpose": "Produce the requested outputs with the appropriate specialist and workspace tools.",
            "specialists": specialists,
        },
        {
            "name": "validate",
            "purpose": "Run deterministic checks and collect evidence rather than trusting completion claims.",
            "quality_gates": quality_gates,
        },
        {
            "name": "repair",
            "purpose": "Fix failed checks, rerun validation, and preserve failure evidence if repair is incomplete.",
        },
        {
            "name": "deliver",
            "purpose": "Return usable artifacts plus concise evidence, limitations, and next actions.",
        },
    ]

    return {
        "ok": True,
        "objective": objective.strip(),
        "artifact_types": selected,
        "specialists": specialists,
        "required_capabilities": capabilities,
        "preferred_tool_hints": preferred_tools,
        "quality_gates": quality_gates,
        "external_actions_allowed": bool(allow_external_actions),
        "execution_policy": {
            "discover_missing_tools": True,
            "prefer_existing_tools_over_new_plugins": True,
            "require_evidence_before_completion": True,
            "repair_failed_validation": True,
            "external_side_effects_require_policy_approval": True,
            "workspace_boundary_required": True,
        },
        "phases": phases,
    }


def register(registry):
    registry.register(
        name="plan_universal_creation",
        description=(
            "Plan a complex DPN AI request that may combine coding, documents, images, research, data, "
            "media, and automation. Returns specialists, capability requirements, quality gates, and tool hints "
            "without performing external side effects."
        ),
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Requested output types such as code, document, image, research, data, media, or automation.",
                },
                "require_validation": {"type": "boolean", "default": True},
                "allow_external_actions": {"type": "boolean", "default": False},
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
        function=build_universal_execution_plan,
        risk="read",
    )
