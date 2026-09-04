from __future__ import annotations

from typing import Any


TASKS = {
    "inspect",
    "compare",
    "document",
    "screen",
    "diagram",
    "chart",
    "video",
    "visual_qa",
    "image_generation_review",
}
INPUT_KINDS = {
    "image",
    "screenshot",
    "document",
    "document_page",
    "diagram",
    "chart",
    "video",
    "video_frame",
    "audio",
    "transcript",
}
ALIASES = {
    "photo": "image",
    "picture": "image",
    "screen": "screenshot",
    "pdf": "document",
    "pdf_page": "document_page",
    "graph": "chart",
    "clip": "video",
    "frame": "video_frame",
}


def _normalize_kinds(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for raw in values or ["image"]:
        value = str(raw or "").strip().lower()
        value = ALIASES.get(value, value)
        if value in INPUT_KINDS and value not in result:
            result.append(value)
    return result or ["image"]


def build_multimodal_vision_plan(
    objective: str,
    task: str = "inspect",
    input_kinds: list[str] | None = None,
    require_cross_check: bool = True,
    allow_generation: bool = False,
    max_visual_inputs: int = 24,
    max_video_frames: int = 32,
    max_iterations: int = 4,
) -> dict[str, Any]:
    normalized_task = str(task or "inspect").strip().lower()
    if normalized_task not in TASKS:
        normalized_task = "inspect"
    kinds = _normalize_kinds(input_kinds)
    visual_cap = max(1, min(int(max_visual_inputs), 64))
    frame_cap = max(1, min(int(max_video_frames), 96))
    iteration_cap = max(0, min(int(max_iterations), 6))

    stages: list[dict[str, str]] = [
        {
            "id": "inventory",
            "goal": "Confirm every referenced multimodal input exists, is accessible, and has source provenance before analysis begins.",
        },
        {
            "id": "extract",
            "goal": "Extract native metadata/text/transcripts first and prepare bounded visual/audio representations without losing page, frame, timestamp, or file identity.",
        },
        {
            "id": "route",
            "goal": "Select only models/providers that actually satisfy required vision, audio, context, and tool capabilities; record the concrete route and any fallback.",
        },
        {
            "id": "observe",
            "goal": "Record direct observations separately from interpretation, including objects, layout, text regions, visual relationships, temporal events, and uncertainty.",
        },
        {
            "id": "fuse",
            "goal": "Fuse compatible evidence across visual, textual, metadata, transcript, and temporal sources while preserving source-level provenance.",
        },
        {
            "id": "reason",
            "goal": "Answer the objective using only supported multimodal evidence, explicitly separating observation, inference, contradiction, and unknowns.",
        },
        {
            "id": "verify",
            "goal": "Cross-check material claims against alternate pages, frames, metadata, extracted text, or an independent capable reviewer when required.",
        },
        {
            "id": "deliver",
            "goal": "Return findings with confidence, provenance, actual model/provider evidence, limitations, and any generated artifacts or comparison outputs.",
        },
    ]

    if normalized_task == "document" or "document" in kinds or "document_page" in kinds:
        stages.insert(
            3,
            {
                "id": "document_context",
                "goal": "Prefer native document text and structure; use page-image reasoning where layout/visual content matters and OCR only as a bounded fallback.",
            },
        )
    if normalized_task == "video" or "video" in kinds or "video_frame" in kinds:
        stages.insert(
            3,
            {
                "id": "temporal_context",
                "goal": "Select bounded keyframes and preserve timestamps; incorporate transcript/audio context when available and never claim unseen intervals.",
            },
        )
    if normalized_task == "compare":
        stages.insert(
            5,
            {
                "id": "alignment",
                "goal": "Align comparable regions/pages/frames before reporting additions, removals, visual differences, or similarity; never claim pixel identity without measurement.",
            },
        )
    if normalized_task == "image_generation_review":
        stages.insert(
            -1,
            {
                "id": "generation_review",
                "goal": "Inspect the actually generated image against the prompt, required text, composition, style, and constraints before claiming completion.",
            },
        )

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "task": normalized_task,
        "input_kinds": kinds,
        "limits": {
            "max_visual_inputs": visual_cap,
            "max_video_frames": frame_cap,
            "max_iterations": iteration_cap,
        },
        "required_capabilities": [
            "multimodal_ingestion",
            "vision_analysis",
            "model_routing",
            "provenance",
            "evidence_validation",
        ],
        "quality_gates": [
            "inputs_present_and_decodable",
            "actual_capabilities_verified",
            "actual_model_and_provider_recorded",
            "source_provenance_preserved",
            "observation_and_inference_separated",
            "important_claims_cross_checked",
            "uncertainty_reported",
            "generated_visuals_inspected_before_completion",
        ],
        "execution_policy": {
            "require_real_visual_input_for_visual_claims": True,
            "never_reason_from_filename_or_description_as_visual_evidence": True,
            "never_silently_fallback_to_text_only_for_visual_tasks": True,
            "native_extraction_before_ocr": True,
            "ocr_is_fallback_not_default": True,
            "preserve_page_frame_timestamp_file_provenance": True,
            "record_actual_model_provider_and_fallbacks": True,
            "do_not_claim_unseen_video_intervals": True,
            "do_not_claim_pixel_perfect_match_without_measurement": True,
            "generation_allowed": bool(allow_generation),
            "generated_images_require_post_generation_vision_review": True,
            "external_provider_use_requires_existing_permission": True,
            "bounded_inputs_and_iterations_required": True,
            "cross_check_required": bool(require_cross_check),
        },
        "stages": stages,
    }


def evaluate_multimodal_evidence(
    *,
    inputs_present: bool,
    decoded: bool,
    actual_model: str | None,
    actual_provider: str | None,
    provenance_preserved: bool,
    observations_recorded: bool,
    cross_checked: bool,
    uncertainty_reported: bool,
    generated_visual_inspected: bool = True,
) -> dict[str, Any]:
    checks = {
        "inputs_present_and_decodable": bool(inputs_present and decoded),
        "actual_model_and_provider_recorded": bool(str(actual_model or "").strip() and str(actual_provider or "").strip()),
        "source_provenance_preserved": bool(provenance_preserved),
        "observations_recorded": bool(observations_recorded),
        "important_claims_cross_checked": bool(cross_checked),
        "uncertainty_reported": bool(uncertainty_reported),
        "generated_visuals_inspected_before_completion": bool(generated_visual_inspected),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not failed,
        "status": "pass" if not failed else "fail",
        "checks": checks,
        "failed_gates": failed,
    }


def register(registry) -> None:
    registry.register(
        name="plan_multimodal_vision_v7",
        description="Plan evidence-backed multimodal vision work across images, screenshots, documents, diagrams, charts, video, audio/transcripts, and generated-image review with strict provenance and model-capability verification.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "task": {"type": "string"},
                "input_kinds": {"type": "array", "items": {"type": "string"}},
                "require_cross_check": {"type": "boolean", "default": True},
                "allow_generation": {"type": "boolean", "default": False},
                "max_visual_inputs": {"type": "integer", "default": 24},
                "max_video_frames": {"type": "integer", "default": 32},
                "max_iterations": {"type": "integer", "default": 4},
            },
            "required": ["objective"],
        },
        function=build_multimodal_vision_plan,
        risk="read",
    )
    registry.register(
        name="evaluate_multimodal_evidence_v7",
        description="Evaluate whether multimodal/vision work has enough concrete evidence to claim successful completion.",
        parameters={
            "type": "object",
            "properties": {
                "inputs_present": {"type": "boolean"},
                "decoded": {"type": "boolean"},
                "actual_model": {"type": ["string", "null"]},
                "actual_provider": {"type": ["string", "null"]},
                "provenance_preserved": {"type": "boolean"},
                "observations_recorded": {"type": "boolean"},
                "cross_checked": {"type": "boolean"},
                "uncertainty_reported": {"type": "boolean"},
                "generated_visual_inspected": {"type": "boolean", "default": True},
            },
            "required": [
                "inputs_present",
                "decoded",
                "provenance_preserved",
                "observations_recorded",
                "cross_checked",
                "uncertainty_reported",
            ],
        },
        function=evaluate_multimodal_evidence,
        risk="read",
    )
