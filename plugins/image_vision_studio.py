from __future__ import annotations

from typing import Any


_MODES = {"generate", "edit", "analyze", "iterate"}
_BACKENDS = {"auto", "comfyui", "local", "external"}


def build_image_vision_plan(
    objective: str,
    mode: str = "generate",
    backend: str = "auto",
    reference_images: list[str] | None = None,
    require_feedback_loop: bool = True,
    max_iterations: int = 3,
) -> dict[str, Any]:
    mode = str(mode or "generate").strip().lower()
    backend = str(backend or "auto").strip().lower()
    if mode not in _MODES:
        mode = "generate"
    if backend not in _BACKENDS:
        backend = "auto"
    references = [str(item).strip() for item in (reference_images or []) if str(item).strip()]
    if mode in {"edit", "analyze"} and not references:
        input_requirement = "reference_image_required"
    else:
        input_requirement = "ready"
    iterations = max(0, min(int(max_iterations), 5))
    if not require_feedback_loop:
        iterations = 0

    stages = [
        {"name": "understand", "purpose": "Extract subject, composition, style, dimensions, text, brand, and fidelity requirements."},
        {"name": "inspect_inputs", "purpose": "Inspect reference images and preserve requested identity, layout, or visual constraints.", "required": mode in {"edit", "analyze"}},
        {"name": "route_backend", "purpose": "Choose an available image backend without silently changing providers or permission boundaries.", "backend_preference": backend},
        {"name": "compose_prompt", "purpose": "Build a production prompt, negative prompt, output naming plan, and reproducible seed strategy."},
    ]
    if mode != "analyze":
        stages.append({"name": "render", "purpose": "Generate or edit image assets and persist exact workspace paths."})
    stages.append({"name": "validate", "purpose": "Verify file existence, image signature, dimensions, format, and requested metadata."})
    if iterations:
        stages.append({"name": "vision_feedback", "purpose": "Evaluate output against requirements, identify defects, refine prompt/settings, and rerender within the bounded iteration budget.", "max_iterations": iterations})
    stages.append({"name": "deliver", "purpose": "Return best validated image paths, seed/backend metadata, limitations, and comparison notes."})

    return {
        "ok": True,
        "objective": objective.strip(),
        "mode": mode,
        "backend": backend,
        "reference_images": references,
        "input_requirement": input_requirement,
        "required_capabilities": ["image_generation", "image_editing", "vision_analysis", "media_validation", "workspace"],
        "quality_gates": ["artifact_exists", "image_decodes", "dimensions_valid", "format_valid", "prompt_requirements_met"],
        "feedback_loop": {"enabled": bool(iterations), "max_iterations": iterations, "stop_on_validated_match": True},
        "execution_policy": {
            "do_not_claim_visual_match_without_evidence": True,
            "preserve_reference_constraints": True,
            "record_seed_and_backend": True,
            "exact_workspace_paths_required": True,
            "backend_fallback_must_be_reported": True,
            "external_side_effects_require_policy_approval": True,
        },
        "stages": stages,
    }


def register(registry):
    registry.register(
        name="plan_image_vision_mission",
        description="Plan an image generation, editing, analysis, or iterative vision mission with backend routing, validation, and bounded visual feedback loops.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["generate", "edit", "analyze", "iterate"], "default": "generate"},
                "backend": {"type": "string", "enum": ["auto", "comfyui", "local", "external"], "default": "auto"},
                "reference_images": {"type": "array", "items": {"type": "string"}, "default": []},
                "require_feedback_loop": {"type": "boolean", "default": True},
                "max_iterations": {"type": "integer", "minimum": 0, "maximum": 5, "default": 3}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_image_vision_plan,
        risk="read",
    )
