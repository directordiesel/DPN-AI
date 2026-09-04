from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


_FORMATS: dict[str, dict[str, Any]] = {
    ".pdf": {"kind": "document", "route": "document-artifact-studio-v6", "capabilities": ["document_extraction", "citation_provenance"]},
    ".docx": {"kind": "document", "route": "document-artifact-studio-v6", "capabilities": ["office_document_reading", "structure_extraction"]},
    ".xlsx": {"kind": "spreadsheet", "route": "document-artifact-studio-v6", "capabilities": ["spreadsheet_reading", "table_extraction", "formula_awareness"]},
    ".pptx": {"kind": "presentation", "route": "document-artifact-studio-v6", "capabilities": ["presentation_reading", "slide_structure"]},
    ".png": {"kind": "image", "route": "image-vision-studio-v6", "capabilities": ["vision_analysis", "image_metadata"]},
    ".jpg": {"kind": "image", "route": "image-vision-studio-v6", "capabilities": ["vision_analysis", "image_metadata"]},
    ".jpeg": {"kind": "image", "route": "image-vision-studio-v6", "capabilities": ["vision_analysis", "image_metadata"]},
    ".webp": {"kind": "image", "route": "image-vision-studio-v6", "capabilities": ["vision_analysis", "image_metadata"]},
    ".wav": {"kind": "audio", "route": "media", "capabilities": ["media_probe", "speech_context"]},
    ".mp3": {"kind": "audio", "route": "media", "capabilities": ["media_probe", "speech_context"]},
    ".m4a": {"kind": "audio", "route": "media", "capabilities": ["media_probe", "speech_context"]},
    ".flac": {"kind": "audio", "route": "media", "capabilities": ["media_probe", "speech_context"]},
    ".mp4": {"kind": "video", "route": "media", "capabilities": ["media_probe", "keyframe_extraction", "speech_context"]},
    ".mov": {"kind": "video", "route": "media", "capabilities": ["media_probe", "keyframe_extraction", "speech_context"]},
    ".mkv": {"kind": "video", "route": "media", "capabilities": ["media_probe", "keyframe_extraction", "speech_context"]},
    ".webm": {"kind": "video", "route": "media", "capabilities": ["media_probe", "keyframe_extraction", "speech_context"]},
    ".zip": {"kind": "archive", "route": "repository-intelligence-v6", "capabilities": ["archive_inspection", "bounded_extraction", "tree_inventory"]},
    ".tar": {"kind": "archive", "route": "repository-intelligence-v6", "capabilities": ["archive_inspection", "bounded_extraction", "tree_inventory"]},
    ".tgz": {"kind": "archive", "route": "repository-intelligence-v6", "capabilities": ["archive_inspection", "bounded_extraction", "tree_inventory"]},
    ".log": {"kind": "log", "route": "coding-agent-v6", "capabilities": ["text_reading", "error_pattern_analysis"]},
    ".txt": {"kind": "text", "route": "research-browser-agent-v6", "capabilities": ["text_reading", "knowledge_indexing"]},
    ".md": {"kind": "text", "route": "research-browser-agent-v6", "capabilities": ["text_reading", "knowledge_indexing"]},
    ".json": {"kind": "structured_data", "route": "coding-agent-v6", "capabilities": ["structured_data_reading", "schema_awareness"]},
    ".csv": {"kind": "structured_data", "route": "document-artifact-studio-v6", "capabilities": ["table_extraction", "data_validation"]},
    ".py": {"kind": "code", "route": "coding-agent-v6", "capabilities": ["source_reading", "dependency_analysis"]},
    ".js": {"kind": "code", "route": "coding-agent-v6", "capabilities": ["source_reading", "dependency_analysis"]},
    ".ts": {"kind": "code", "route": "coding-agent-v6", "capabilities": ["source_reading", "dependency_analysis"]},
    ".lua": {"kind": "code", "route": "coding-agent-v6", "capabilities": ["source_reading", "dependency_analysis"]},
}


def classify_input(path: str) -> dict[str, Any]:
    clean = str(path or "").strip().replace("\\", "/")
    suffix = PurePosixPath(clean).suffix.lower()
    profile = _FORMATS.get(suffix)
    if not profile:
        return {
            "path": clean,
            "kind": "unknown",
            "route": "universal-creator-v6",
            "capabilities": ["file_inspection", "tool_discovery"],
            "supported": False,
        }
    return {"path": clean, "extension": suffix, "supported": True, **profile}


def build_multimodal_ingestion_plan(
    objective: str,
    inputs: list[str] | None = None,
    recursive: bool = False,
    preserve_provenance: bool = True,
    max_files: int = 100,
    max_media_frames: int = 6,
) -> dict[str, Any]:
    files = [str(item).strip() for item in (inputs or []) if str(item).strip()]
    max_files = max(1, min(int(max_files), 500))
    max_media_frames = max(1, min(int(max_media_frames), 12))
    classified = [classify_input(item) for item in files[:max_files]]
    kinds = sorted({item["kind"] for item in classified})
    routes = sorted({item["route"] for item in classified})
    capabilities = sorted({cap for item in classified for cap in item["capabilities"]})
    unknown = [item["path"] for item in classified if not item["supported"]]

    stages = [
        {"name": "inventory", "purpose": "Enumerate supplied files/folders within workspace boundaries and enforce file-count limits.", "recursive": bool(recursive), "max_files": max_files},
        {"name": "classify", "purpose": "Classify each input by real extension/container role and select the safest existing specialist route."},
        {"name": "inspect", "purpose": "Read metadata and structure before expensive extraction; reject missing, corrupt, mislabeled, or unsupported inputs explicitly."},
        {"name": "extract", "purpose": "Extract bounded text, tables, slides, image context, media keyframes/speech context, logs, code, or archive inventories using existing tools."},
        {"name": "normalize", "purpose": "Convert extracted evidence into a common manifest without flattening source-specific structure or losing page/sheet/slide/file provenance."},
        {"name": "route", "purpose": "Send normalized evidence to the appropriate coding, artifact, vision, research, repository, or media specialist."},
        {"name": "correlate", "purpose": "Cross-reference facts and entities across mixed inputs while keeping conflicting evidence visible."},
        {"name": "validate", "purpose": "Verify every claimed source was actually read or extracted and that generated derivatives have exact workspace paths."},
        {"name": "deliver", "purpose": "Return findings, provenance manifest, routed specialist results, unsupported inputs, extraction limits, and exact output paths."},
    ]

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "inputs": classified,
        "input_kinds": kinds,
        "specialist_routes": routes,
        "required_capabilities": capabilities,
        "unsupported_inputs": unknown,
        "media_policy": {"max_frames_per_video": max_media_frames, "speech_context_is_bounded": True},
        "quality_gates": [
            "source_exists",
            "source_type_verified",
            "extraction_evidence_present",
            "provenance_preserved",
            "unsupported_inputs_disclosed",
            "derived_paths_reported",
        ],
        "execution_policy": {
            "workspace_boundary_required": True,
            "preserve_provenance": bool(preserve_provenance),
            "do_not_claim_unread_content": True,
            "do_not_treat_filename_as_content_evidence": True,
            "do_not_execute_ingested_code": True,
            "archives_must_be_inspected_before_extraction": True,
            "archive_extraction_must_be_bounded": True,
            "media_analysis_must_be_bounded": True,
            "corrupt_or_unsupported_files_must_be_reported": True,
            "original_inputs_are_read_only_by_default": True,
        },
        "stages": stages,
    }


def register(registry):
    registry.register(
        name="plan_multimodal_ingestion",
        description="Plan safe multimodal ingestion of documents, images, media, logs, code, archives, structured data, and mixed project folders with provenance-preserving specialist routing.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "inputs": {"type": "array", "items": {"type": "string"}, "default": []},
                "recursive": {"type": "boolean", "default": False},
                "preserve_provenance": {"type": "boolean", "default": True},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                "max_media_frames": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_multimodal_ingestion_plan,
        risk="read",
    )
