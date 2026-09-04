from __future__ import annotations

from typing import Any


PREVIEW_TYPES = {
    "document": {"formats": ["docx", "pdf", "txt", "md"], "checks": ["artifact_exists", "artifact_valid", "preview_representation_available"]},
    "spreadsheet": {"formats": ["xlsx", "csv"], "checks": ["artifact_exists", "artifact_valid", "sheet_structure_available"]},
    "presentation": {"formats": ["pptx"], "checks": ["artifact_exists", "artifact_valid", "slide_structure_available"]},
    "image": {"formats": ["png", "jpg", "jpeg", "webp", "gif"], "checks": ["artifact_exists", "image_decodes", "dimensions_available"]},
    "media": {"formats": ["mp3", "wav", "m4a", "mp4", "mov", "mkv", "webm"], "checks": ["artifact_exists", "media_probe_available"]},
    "code": {"formats": ["py", "js", "ts", "lua", "go", "rs", "java", "cs", "html", "css", "json", "yaml", "yml"], "checks": ["artifact_exists", "safe_text_preview"]},
    "archive": {"formats": ["zip", "tar", "tgz"], "checks": ["artifact_exists", "archive_inventory_available"]},
}

ALIASES = {"word": "document", "pdf": "document", "excel": "spreadsheet", "powerpoint": "presentation", "photo": "image", "video": "media", "audio": "media", "source": "code"}
MODES = {"preview", "compare", "review", "gallery", "handoff"}


def _normalize_type(value: str) -> str:
    item = str(value or "").strip().lower()
    return ALIASES.get(item, item)


def build_artifact_preview_plan(
    objective: str,
    artifact_types: list[str] | None = None,
    mode: str = "preview",
    require_validation: bool = True,
    max_items: int = 24,
    allow_active_content: bool = False,
) -> dict[str, Any]:
    normalized_mode = str(mode or "preview").strip().lower()
    if normalized_mode not in MODES:
        normalized_mode = "preview"
    selected: list[str] = []
    for item in artifact_types or ["document", "spreadsheet", "presentation", "image", "media", "code"]:
        value = _normalize_type(item)
        if value in PREVIEW_TYPES and value not in selected:
            selected.append(value)
    if not selected:
        selected = ["document"]
    item_cap = max(1, min(int(max_items), 100))

    checks: list[str] = []
    formats: list[str] = []
    for kind in selected:
        checks.extend(PREVIEW_TYPES[kind]["checks"])
        formats.extend(PREVIEW_TYPES[kind]["formats"])
    if require_validation:
        checks.extend(["source_path_reported", "validation_evidence_attached"])

    stages = [
        {"id": "inventory", "goal": "Inventory candidate artifacts and exact workspace-relative paths; do not infer previewability from filenames alone."},
        {"id": "validate", "goal": "Run the strongest native structural/media/image validation available before exposing preview-ready status."},
        {"id": "sanitize", "goal": "Treat previews as passive content. Do not execute macros, scripts, embedded code, remote references, or archive members."},
        {"id": "represent", "goal": "Choose the safest useful representation: native metadata/structure first, bounded text/image/media representation second, conversion only when a trusted local tool exists."},
        {"id": "annotate", "goal": "Attach source path, format, size, validation state, provenance, warnings, and generated derivative paths to each preview item."},
        {"id": "experience", "goal": "Present preview items with capability-aware actions such as inspect, compare, revise, validate, export, or open source location without implying unsupported editing."},
        {"id": "deliver", "goal": "Return preview-ready items, blocked items, validation evidence, limitations, and exact safe next actions."},
    ]
    if normalized_mode == "compare":
        stages.insert(5, {"id": "comparison", "goal": "Compare validated representations using stable identifiers and surface differences without rewriting sources."})
    if normalized_mode == "gallery":
        stages.insert(5, {"id": "grouping", "goal": "Group preview items by type, project, provenance, or mission while preserving exact source identity."})

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "mode": normalized_mode,
        "artifact_types": selected,
        "supported_formats": list(dict.fromkeys(formats)),
        "limits": {"max_items": item_cap},
        "quality_gates": list(dict.fromkeys(checks)),
        "execution_policy": {
            "validation_required_before_preview_ready_claim": bool(require_validation),
            "active_content_allowed": bool(allow_active_content),
            "execute_embedded_code_or_macros": False,
            "follow_remote_embedded_references": False,
            "extract_archive_members_implicitly": False,
            "mutate_source_during_preview": False,
            "preview_derivatives_must_remain_in_workspace": True,
            "exact_source_path_required": True,
            "blocked_or_unsupported_items_must_be_visible": True,
            "do_not_claim_edit_support_from_preview_support": True,
            "do_not_claim_visual_fidelity_without_render_evidence": True,
        },
        "stages": stages,
    }


def register(registry) -> None:
    registry.register(
        name="plan_artifact_preview_experience",
        description="Plan safe validated previews and capability-aware artifact experiences for documents, spreadsheets, presentations, images, media, code, and archives.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "artifact_types": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "require_validation": {"type": "boolean", "default": True},
                "max_items": {"type": "integer", "default": 24},
                "allow_active_content": {"type": "boolean", "default": False}
            },
            "required": ["objective"]
        },
        function=build_artifact_preview_plan,
        risk="read"
    )
