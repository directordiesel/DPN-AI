from __future__ import annotations

import os
from pathlib import Path

from app.model_gateway import ModelGateway
from app.tools.image_vision_providers import ComfyUIImageEditor, ConfigurableVisionProvider


def register(registry):
    gateway = ModelGateway(registry.settings, registry.db, registry.vault)
    vision = ConfigurableVisionProvider(
        gateway,
        registry.settings.workspace_dir,
        configured_model=os.getenv("DPN_VISION_MODEL", "").strip(),
    )
    edit_workflow = os.getenv("DPN_COMFYUI_EDIT_WORKFLOW", "").strip()
    editor = ComfyUIImageEditor(
        registry.settings.comfyui_url,
        Path(edit_workflow) if edit_workflow else "",
        registry.settings.workspace_dir,
    )

    registry.register(
        name="analyze_image_with_vision",
        description="Analyze one workspace image through an explicitly configured vision-capable model. Fails closed when no DPN_VISION_MODEL or explicit model is configured.",
        parameters={
            "type": "object",
            "properties": {
                "reference_image": {"type": "string", "minLength": 1},
                "prompt": {"type": "string", "default": "Analyze this image accurately and describe the important visual evidence."},
                "model": {"type": "string", "default": ""}
            },
            "required": ["reference_image"],
            "additionalProperties": False
        },
        function=vision.analyze,
        gate="images",
        risk="external",
    )

    registry.register(
        name="edit_image_with_comfyui",
        description="Edit a workspace image through a user-supplied ComfyUI API img2img/edit workflow. Fails closed until DPN_COMFYUI_EDIT_WORKFLOW points to a valid workflow.",
        parameters={
            "type": "object",
            "properties": {
                "reference_image": {"type": "string", "minLength": 1},
                "prompt": {"type": "string", "minLength": 1},
                "negative_prompt": {"type": "string", "default": "low quality, blurry, distorted, watermark, text artifacts"},
                "filename_prefix": {"type": "string", "default": "DPN_AI_EDIT"},
                "seed": {"type": ["integer", "null"], "default": None},
                "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 1800, "default": 300}
            },
            "required": ["reference_image", "prompt"],
            "additionalProperties": False
        },
        function=editor.edit,
        gate="images",
        risk="external",
    )
