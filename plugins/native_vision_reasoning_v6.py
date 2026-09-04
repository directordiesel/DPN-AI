from __future__ import annotations

from typing import Any


MODES = {"inspect", "compare", "document", "screen", "video", "diagram", "qa"}
INPUT_KINDS = {"image", "document_page", "screenshot", "video_frame", "diagram", "chart"}
ALIASES = {"photo": "image", "picture": "image", "pdf_page": "document_page", "screen": "screenshot", "frame": "video_frame", "graph": "chart"}


def build_native_vision_reasoning_plan(
    objective: str,
    mode: str = "inspect",
    input_kinds: list[str] | None = None,
    require_vision_model: bool = True,
    require_cross_check: bool = True,
    max_inputs: int = 20,
    max_iterations: int = 3,
) -> dict[str, Any]:
    normalized_mode = str(mode or "inspect").strip().lower()
    if normalized_mode not in MODES:
        normalized_mode = "inspect"
    kinds: list[str] = []
    for item in input_kinds or ["image"]:
        value = ALIASES.get(str(item or "").strip().lower(), str(item or "").strip().lower())
        if value in INPUT_KINDS and value not in kinds:
            kinds.append(value)
    if not kinds:
        kinds = ["image"]
    input_cap = max(1, min(int(max_inputs), 50))
    iteration_cap = max(0, min(int(max_iterations), 5))

    stages = [
        {"id": "inventory", "goal": "Inventory exact visual inputs and provenance. Reject missing inputs instead of reasoning from filenames or descriptions alone."},
        {"id": "prepare", "goal": "Decode/validate images or prepare bounded document pages/video frames with exact source references before model analysis."},
        {"id": "route_model", "goal": "Discover an actually available vision-capable model through the model router; do not silently downgrade to text-only reasoning."},
        {"id": "observe", "goal": "Record directly visible evidence first: layout, objects, text regions, relationships, measurements available from metadata, and uncertainty."},
        {"id": "reason", "goal": "Answer the objective using observed visual evidence while explicitly separating observation, inference, and unknowns."},
        {"id": "cross_check", "goal": "Cross-check important visual claims against metadata, extracted text, alternate frames/pages, or another capable reviewer when available."},
        {"id": "iterate", "goal": "If evidence is insufficient or contradictory, inspect additional bounded inputs or refine the question within the iteration budget."},
        {"id": "deliver", "goal": "Return findings with source-level provenance, confidence, unresolved ambiguity, actual model/provider evidence, and any generated comparison artifacts."},
    ]
    if normalized_mode == "compare":
        stages.insert(5, {"id": "alignment", "goal": "Align comparable regions/frames/pages and report additions, removals, changes, and uncertainty without claiming pixel identity unless measured."})
    if normalized_mode == "document":
        stages.insert(3, {"id": "page_context", "goal": "Combine native text extraction with page-image reasoning; use OCR only when native extraction is unavailable or insufficient."})
    if normalized_mode == "video":
        stages.insert(3, {"id": "temporal_context", "goal": "Use bounded keyframes, timestamps, probe metadata, and available transcript/audio context; do not infer unseen intervals."})

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "mode": normalized_mode,
        "input_kinds": kinds,
        "limits": {"max_inputs": input_cap, "max_iterations": iteration_cap},
        "required_capabilities": ["vision_analysis", "multimodal_ingestion", "model_routing", "provenance", "evidence_validation"],
        "quality_gates": [
            "inputs_exist_and_decode", "vision_capability_verified", "source_provenance_preserved",
            "observation_inference_separated", "important_claims_cross_checked", "actual_model_recorded",
            "uncertainty_reported"
        ],
        "execution_policy": {
            "vision_model_required": bool(require_vision_model),
            "cross_check_required": bool(require_cross_check),
            "do_not_reason_from_missing_visual_input": True,
            "do_not_silently_use_text_only_model_for_visual_claims": True,
            "native_text_extraction_before_ocr": True,
            "ocr_is_fallback_not_default": True,
            "do_not_claim_pixel_perfect_match_without_measurement": True,
            "do_not_claim_unseen_video_intervals": True,
            "record_actual_model_and_provider": True,
            "preserve_page_frame_timestamp_provenance": True,
            "external_model_use_requires_existing_policy_permission": True,
            "bounded_iteration_required": True,
        },
        "stages": stages,
    }


def register(registry) -> None:
    registry.register(
        name="plan_native_vision_reasoning",
        description="Plan evidence-backed native visual reasoning across images, document pages, screenshots, diagrams, charts, and bounded video frames with real vision-model routing and provenance.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "mode": {"type": "string"},
                "input_kinds": {"type": "array", "items": {"type": "string"}},
                "require_vision_model": {"type": "boolean", "default": True},
                "require_cross_check": {"type": "boolean", "default": True},
                "max_inputs": {"type": "integer", "default": 20},
                "max_iterations": {"type": "integer", "default": 3}
            },
            "required": ["objective"]
        },
        function=build_native_vision_reasoning_plan,
        risk="read"
    )
