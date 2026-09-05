from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Mapping

from app.config import Settings


@dataclass(frozen=True)
class CapabilityReadiness:
    name: str
    implemented: bool
    configured: bool
    permission_enabled: bool
    live: bool
    reason: str

    def payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityRegistry:
    capabilities: tuple[CapabilityReadiness, ...]

    def payload(self) -> dict[str, object]:
        return {
            "capabilities": [item.payload() for item in self.capabilities],
            "summary": {
                "total": len(self.capabilities),
                "implemented": sum(item.implemented for item in self.capabilities),
                "configured": sum(item.configured for item in self.capabilities),
                "permission_enabled": sum(item.permission_enabled for item in self.capabilities),
                "live": sum(item.live for item in self.capabilities),
            },
        }


def _clean_env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _verified_live(
    name: str,
    *,
    implemented: bool,
    configured: bool,
    permission_enabled: bool,
    verified_live: Mapping[str, bool],
) -> bool:
    # A caller may provide a live result only after performing its own trusted,
    # capability-specific health check. Configuration alone never implies live.
    return bool(
        implemented
        and configured
        and permission_enabled
        and verified_live.get(name) is True
    )


def build_capability_registry(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    verified_live: Mapping[str, bool] | None = None,
) -> CapabilityRegistry:
    if not isinstance(settings, Settings):
        raise TypeError("settings must be a Settings instance")
    env = _clean_env(environ)
    live_results = {} if verified_live is None else dict(verified_live)

    vision_model = str(env.get("DPN_VISION_MODEL", "")).strip()
    edit_workflow = str(env.get("DPN_COMFYUI_EDIT_WORKFLOW", "")).strip()
    compatible_url = str(settings.compatible_api_url or "").strip()

    specs = (
        (
            "local_models",
            True,
            bool(str(settings.ollama_url or "").strip() and str(settings.default_model or "").strip()),
            True,
            "Local model routing is implemented; live status requires a successful provider health check.",
        ),
        (
            "external_models",
            True,
            bool(compatible_url),
            bool(settings.allow_external_models_default),
            "External model routing requires an explicit compatible API URL and external-model permission.",
        ),
        (
            "vision",
            True,
            bool(vision_model),
            bool(settings.allow_images_default),
            "Vision remains unavailable until DPN_VISION_MODEL is configured and image permission is enabled.",
        ),
        (
            "image_editing",
            True,
            bool(edit_workflow),
            bool(settings.allow_images_default),
            "Image editing remains unavailable until DPN_COMFYUI_EDIT_WORKFLOW is configured and image permission is enabled.",
        ),
        (
            "automations",
            True,
            True,
            bool(settings.allow_automations_default),
            "Automation execution is local but remains permission gated.",
        ),
        (
            "desktop_control",
            True,
            True,
            bool(settings.allow_desktop_default),
            "Desktop control is implemented but remains permission gated and highest-risk actions still require fresh approval.",
        ),
        (
            "voice",
            True,
            True,
            bool(settings.allow_voice_default),
            "Voice session support is implemented; live capture/playback requires independently verified platform providers.",
        ),
        (
            "connectors",
            True,
            True,
            bool(settings.allow_connectors_default),
            "Connector use is implemented but remains permission gated; individual connector availability is not inferred.",
        ),
        (
            "mcp",
            True,
            True,
            bool(settings.allow_mcp_default),
            "MCP support is implemented but remains permission gated; server availability is not inferred.",
        ),
        (
            "host_sandbox",
            True,
            True,
            bool(settings.allow_host_sandbox_default),
            "Host sandbox fallback is implemented but remains explicitly permission gated.",
        ),
    )

    capabilities: list[CapabilityReadiness] = []
    for name, implemented, configured, permission_enabled, reason in specs:
        capabilities.append(
            CapabilityReadiness(
                name=name,
                implemented=implemented,
                configured=configured,
                permission_enabled=permission_enabled,
                live=_verified_live(
                    name,
                    implemented=implemented,
                    configured=configured,
                    permission_enabled=permission_enabled,
                    verified_live=live_results,
                ),
                reason=reason,
            )
        )
    return CapabilityRegistry(capabilities=tuple(capabilities))


__all__ = [
    "CapabilityReadiness",
    "CapabilityRegistry",
    "build_capability_registry",
]
