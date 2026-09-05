from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.model_routing_v9 import (
    ModelCandidate,
    ModelCapability,
    ModelRoutingPolicy,
    ProviderClass,
    RoutingDecision,
    RoutingRequest,
)


@dataclass(frozen=True)
class ModelRouteContext:
    profile: str = "auto"
    require_vision: bool = False
    require_tools: bool = False
    prefer_local: bool = True
    allow_remote: bool = False
    requested_model: str = ""
    fallback_model: str = ""


class ModelRoutingRuntime:
    """Adapt ModelGateway inventory records to the v9 deterministic router."""

    def __init__(self, *, max_fallbacks: int = 3) -> None:
        self.policy = ModelRoutingPolicy(max_fallbacks=max_fallbacks)

    @staticmethod
    def _capabilities(item: dict[str, Any], profile: str) -> frozenset[ModelCapability]:
        name = str(item.get("name") or item.get("model") or "").lower()
        caps = {ModelCapability.CHAT}
        if any(token in name for token in ("vision", "llava", "-vl", "qwen-vl", "gemma3", "llama4", "qwen3.5")):
            caps.add(ModelCapability.VISION)
        if not any(token in name for token in ("embed", "embedding", "nomic-embed", "bge-", "snowflake-arctic-embed")):
            caps.add(ModelCapability.TOOLS)
        else:
            caps.discard(ModelCapability.CHAT)
            caps.add(ModelCapability.EMBEDDINGS)
        if any(token in name for token in ("reason", "deepseek-r1", "qwen3", "qwen3.5", "o1", "o3")):
            caps.add(ModelCapability.REASONING)
        if any(token in name for token in ("coder", "code", "qwen2.5-coder", "qwen3")) or profile in {"software", "fivem"}:
            caps.add(ModelCapability.CODE)
        return frozenset(caps)

    @classmethod
    def candidates_from_inventory(
        cls,
        items: Iterable[dict[str, Any]],
        *,
        profile: str = "auto",
        compatible_is_local: bool = False,
    ) -> list[ModelCandidate]:
        output: list[ModelCandidate] = []
        for index, item in enumerate(items):
            name = str(item.get("name") or item.get("model") or "").strip()
            provider = str(item.get("provider") or "ollama").strip().lower()
            if not name or provider not in {"ollama", "compatible"}:
                continue
            provider_class = ProviderClass.LOCAL if provider == "ollama" or compatible_is_local else ProviderClass.REMOTE
            output.append(
                ModelCandidate(
                    name=name,
                    provider=provider,
                    provider_class=provider_class,
                    capabilities=cls._capabilities(item, profile),
                    healthy=bool(item.get("healthy", True)),
                    priority=index,
                    latency_ms=item.get("latency_ms") if isinstance(item.get("latency_ms"), int) and not isinstance(item.get("latency_ms"), bool) else None,
                    cost_weight=float(item.get("cost_weight") or 0.0) if not isinstance(item.get("cost_weight"), bool) else 0.0,
                )
            )
        return output

    def decide(
        self,
        items: Iterable[dict[str, Any]],
        context: ModelRouteContext,
        *,
        compatible_is_local: bool = False,
    ) -> RoutingDecision:
        required = {ModelCapability.CHAT}
        if context.require_vision:
            required.add(ModelCapability.VISION)
        if context.require_tools:
            required.add(ModelCapability.TOOLS)
        if context.profile in {"software", "fivem"}:
            required.add(ModelCapability.CODE)
        candidates = self.candidates_from_inventory(items, profile=context.profile, compatible_is_local=compatible_is_local)
        return self.policy.decide(
            candidates,
            RoutingRequest(
                required_capabilities=frozenset(required),
                prefer_local=context.prefer_local,
                allow_remote=context.allow_remote,
                requested_model=context.requested_model,
                fallback_model=context.fallback_model,
            ),
        )


__all__ = ["ModelRouteContext", "ModelRoutingRuntime"]
