from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.image_intelligence import ImageIntelligence


ProviderCallback = Callable[..., Any] | Callable[..., Awaitable[Any]]


class ImageProviderRuntime:
    """Capability-aware image runtime with fail-closed edit and vision boundaries."""

    def __init__(
        self,
        workspace,
        *,
        generate: ProviderCallback | None = None,
        edit: ProviderCallback | None = None,
        analyze: ProviderCallback | None = None,
    ) -> None:
        self.intelligence = ImageIntelligence(workspace)
        self.generate_callback = generate
        self.edit_callback = edit
        self.analyze_callback = analyze

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "capabilities": {
                "text_to_image": self.generate_callback is not None,
                "image_edit": self.edit_callback is not None,
                "vision": self.analyze_callback is not None,
            },
            "policy": {
                "workspace_images_only": True,
                "edit_requires_source": True,
                "vision_requires_source": True,
                "unsupported_capabilities_fail_closed": True,
            },
        }

    def plan(
        self,
        operation: str,
        prompt: str,
        source_path: str | None = None,
        mask_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        request = self.intelligence.build_request(
            operation,
            prompt,
            source_path=source_path,
            mask_path=mask_path,
            width=width,
            height=height,
        )
        capability = request["provider_capability"]
        available = self.capabilities()["capabilities"][capability]
        return {**request, "provider_available": available}

    async def execute(
        self,
        operation: str,
        prompt: str,
        source_path: str | None = None,
        mask_path: str | None = None,
        width: int | None = None,
        height: int | None = None,
        negative_prompt: str = "low quality, blurry, distorted, watermark, text artifacts",
        filename_prefix: str = "DPN_AI",
        seed: int | None = None,
    ) -> dict[str, Any]:
        plan = self.plan(
            operation,
            prompt,
            source_path=source_path,
            mask_path=mask_path,
            width=width,
            height=height,
        )
        capability = plan["provider_capability"]
        callback = {
            "text_to_image": self.generate_callback,
            "image_edit": self.edit_callback,
            "vision": self.analyze_callback,
        }[capability]
        if callback is None:
            return {
                "ok": False,
                "operation": plan["operation"],
                "request_id": plan["request_id"],
                "provider_capability": capability,
                "error": f"No configured provider supports {capability}",
            }

        if capability == "text_to_image":
            result = callback(
                prompt=plan["prompt"],
                negative_prompt=negative_prompt,
                filename_prefix=filename_prefix,
                seed=seed,
            )
        elif capability == "image_edit":
            result = callback(
                prompt=plan["prompt"],
                source_path=plan["source_path"],
                mask_path=plan["mask_path"],
                width=plan["width"],
                height=plan["height"],
            )
        else:
            result = callback(prompt=plan["prompt"], source_path=plan["source_path"])

        if hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict):
            return {"ok": False, "error": "Image provider returned an invalid response", "request_id": plan["request_id"]}
        return {**result, "request_id": plan["request_id"], "operation": plan["operation"], "provider_capability": capability}


def install_image_tools(registry: Any) -> ImageProviderRuntime | None:
    """Install v9 image intelligence into a real ToolRegistry; ignore minimal test stubs."""
    register = getattr(registry, "register", None)
    settings = getattr(registry, "settings", None)
    generator = getattr(registry, "images", None)
    if not callable(register) or settings is None:
        return None

    runtime = ImageProviderRuntime(
        settings.workspace_dir,
        generate=getattr(generator, "generate", None),
    )
    registry.image_runtime = runtime

    common = {
        "operation": {"type": "string", "enum": ["generate", "edit", "analyze"]},
        "prompt": {"type": "string", "minLength": 1},
        "source_path": {"type": ["string", "null"], "default": None},
        "mask_path": {"type": ["string", "null"], "default": None},
        "width": {"type": ["integer", "null"], "default": None},
        "height": {"type": ["integer", "null"], "default": None},
    }
    schema = {"type": "object", "properties": common, "required": ["operation", "prompt"], "additionalProperties": False}

    register(
        "image_capabilities",
        "Report which DPN AI image generation, editing, and vision provider capabilities are currently configured.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        runtime.capabilities,
        risk="read",
    )
    register(
        "plan_image_operation",
        "Validate and route a generate, edit, or vision request without executing it.",
        schema,
        runtime.plan,
        risk="read",
    )
    register(
        "execute_image_operation",
        "Execute an image request through a configured provider. Unsupported edit/vision capabilities fail closed.",
        schema,
        runtime.execute,
        gate="images",
        risk="external",
    )
    return runtime
