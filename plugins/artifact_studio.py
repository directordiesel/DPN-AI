from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any


_FORMATS = {
    "docx": {
        "extension": ".docx",
        "required_members": {"[Content_Types].xml", "word/document.xml"},
        "producer_tool": "create_word_document",
        "quality_gates": ["container_valid", "main_document_present", "nonempty_output"],
    },
    "xlsx": {
        "extension": ".xlsx",
        "required_members": {"[Content_Types].xml", "xl/workbook.xml"},
        "producer_tool": "create_spreadsheet",
        "quality_gates": ["container_valid", "workbook_present", "nonempty_output"],
    },
    "pptx": {
        "extension": ".pptx",
        "required_members": {"[Content_Types].xml", "ppt/presentation.xml"},
        "producer_tool": "create_presentation",
        "quality_gates": ["container_valid", "presentation_present", "nonempty_output"],
    },
    "pdf": {
        "extension": ".pdf",
        "producer_tool": "create_pdf",
        "quality_gates": ["pdf_signature_valid", "eof_marker_present", "nonempty_output"],
    },
}

_ALIASES = {
    "word": "docx",
    "document": "docx",
    "excel": "xlsx",
    "spreadsheet": "xlsx",
    "powerpoint": "pptx",
    "presentation": "pptx",
}


def _normalize_formats(formats: list[str] | None) -> list[str]:
    result: list[str] = []
    for raw in formats or []:
        key = _ALIASES.get(str(raw).strip().lower().lstrip("."), str(raw).strip().lower().lstrip("."))
        if key in _FORMATS and key not in result:
            result.append(key)
    return result or ["docx"]


def build_artifact_mission(
    objective: str,
    formats: list[str] | None = None,
    existing_artifacts: list[str] | None = None,
    brand: str = "DPN Technology",
    require_validation: bool = True,
) -> dict[str, Any]:
    selected = _normalize_formats(formats)
    existing = [str(item).strip() for item in existing_artifacts or [] if str(item).strip()]
    mode = "edit" if existing else "create"
    producer_tools = list(dict.fromkeys(_FORMATS[item]["producer_tool"] for item in selected))
    gates = list(dict.fromkeys(gate for item in selected for gate in _FORMATS[item]["quality_gates"]))
    if require_validation:
        gates += ["requested_sections_present", "artifact_path_reported"]
    phases = [
        {"name": "understand", "purpose": "Define audience, purpose, required sections, source material, branding, and output formats."},
        {"name": "inspect", "purpose": "Inspect existing artifacts and source files before editing." if existing else "Inspect relevant source material and workspace context before generation."},
        {"name": "structure", "purpose": "Design the information hierarchy, tables, charts, slides, sheets, and cross-format consistency."},
        {"name": "produce", "purpose": "Create or revise the requested artifacts with the native document tools.", "preferred_tools": producer_tools},
        {"name": "validate", "purpose": "Verify real file structure, required content, non-empty output, and format-specific integrity.", "quality_gates": gates},
        {"name": "repair", "purpose": "Repair failed validation or formatting requirements, then validate again."},
        {"name": "deliver", "purpose": "Return exact artifact paths, validation evidence, limitations, and any source assumptions."},
    ]
    return {
        "ok": True,
        "objective": objective.strip(),
        "mode": mode,
        "formats": selected,
        "existing_artifacts": existing,
        "brand": brand.strip() or "DPN Technology",
        "preferred_tools": producer_tools + ["read_file", "list_files", "search_text", "create_workspace_snapshot"],
        "quality_gates": gates,
        "policy": {
            "inspect_existing_before_edit": True,
            "snapshot_before_overwriting_existing": True,
            "preserve_source_unless_overwrite_requested": True,
            "validate_before_completion_claim": bool(require_validation),
            "report_exact_output_paths": True,
            "cross_format_consistency_required": len(selected) > 1,
        },
        "phases": phases,
    }


def _safe_workspace_path(workspace: Path, raw_path: str) -> Path:
    normalized = str(raw_path).strip().lstrip("/\\")
    if not normalized:
        raise ValueError("Artifact path is required")
    target = (workspace / normalized).resolve()
    try:
        target.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("Artifact path escapes the workspace") from exc
    return target


def validate_artifact(workspace: Path, path: str, expected_format: str | None = None) -> dict[str, Any]:
    try:
        target = _safe_workspace_path(workspace, path)
    except ValueError as exc:
        return {"ok": False, "path": path, "errors": [str(exc)], "checks": []}

    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not target.exists() or not target.is_file():
        return {"ok": False, "path": path, "errors": ["Artifact does not exist"], "checks": []}

    size = target.stat().st_size
    checks.append({"name": "nonempty_output", "ok": size > 0, "details": f"{size} bytes"})
    if size <= 0:
        errors.append("Artifact is empty")

    fmt = (expected_format or target.suffix.lstrip(".")).strip().lower()
    fmt = _ALIASES.get(fmt, fmt)
    if fmt not in _FORMATS:
        errors.append(f"Unsupported artifact format: {fmt or 'unknown'}")
        return {"ok": False, "path": path, "format": fmt, "size": size, "checks": checks, "errors": errors}

    expected_extension = _FORMATS[fmt]["extension"]
    extension_ok = target.suffix.lower() == expected_extension
    checks.append({"name": "extension_matches", "ok": extension_ok, "details": target.suffix.lower()})
    if not extension_ok:
        errors.append(f"Expected {expected_extension} extension")

    if fmt in {"docx", "xlsx", "pptx"}:
        try:
            with zipfile.ZipFile(target, "r") as archive:
                bad_member = archive.testzip()
                members = set(archive.namelist())
                required = _FORMATS[fmt]["required_members"]
                missing = sorted(required - members)
                checks.append({"name": "container_valid", "ok": bad_member is None, "details": bad_member or "zip structure valid"})
                checks.append({"name": "required_members", "ok": not missing, "details": missing or sorted(required)})
                if bad_member is not None:
                    errors.append(f"Corrupt Office container member: {bad_member}")
                if missing:
                    errors.append("Missing required Office package members: " + ", ".join(missing))
        except zipfile.BadZipFile:
            checks.append({"name": "container_valid", "ok": False, "details": "not a valid ZIP/Office package"})
            errors.append("Artifact is not a valid Office Open XML container")
    else:
        data = target.read_bytes()
        signature_ok = data.startswith(b"%PDF-")
        eof_ok = b"%%EOF" in data[-2048:] if data else False
        checks.append({"name": "pdf_signature_valid", "ok": signature_ok})
        checks.append({"name": "eof_marker_present", "ok": eof_ok})
        if not signature_ok:
            errors.append("Missing PDF signature")
        if not eof_ok:
            errors.append("Missing PDF EOF marker")

    return {
        "ok": not errors,
        "path": target.relative_to(workspace.resolve()).as_posix(),
        "format": fmt,
        "size": size,
        "checks": checks,
        "errors": errors,
    }


def register(registry):
    workspace = registry.settings.workspace_dir
    registry.register(
        name="plan_artifact_studio",
        description=(
            "Plan a professional Word, PDF, Excel, or PowerPoint creation/editing mission with structure, branding, "
            "cross-format consistency, snapshot policy, validation gates, repair, and exact-path delivery."
        ),
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "formats": {"type": "array", "items": {"type": "string"}},
                "existing_artifacts": {"type": "array", "items": {"type": "string"}},
                "brand": {"type": "string", "default": "DPN Technology"},
                "require_validation": {"type": "boolean", "default": True},
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
        function=build_artifact_mission,
        risk="read",
    )
    registry.register(
        name="validate_office_artifact",
        description="Validate a generated DOCX, XLSX, PPTX, or PDF structurally before claiming it was created successfully.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "expected_format": {"type": ["string", "null"], "default": None},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        function=lambda path, expected_format=None: validate_artifact(workspace, path, expected_format),
        risk="read",
    )
