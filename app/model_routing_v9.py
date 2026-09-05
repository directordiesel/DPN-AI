from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence


class ModelRoutingError(ValueError):
    """Raised when a v9 model-routing request violates policy."""


class ModelCapability(str, Enum):
    CHAT = "chat"
    TOOLS = "tools"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    REASONING = "reasoning"
    CODE = "code"


class ProviderClass(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    provider: str
    provider_class: ProviderClass
    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)
    healthy: bool = True
    priority: int = 100
    latency_ms: int | None = None
    cost_weight: float = 0.0

    def validate(self) -> None:
        if not self.name.strip():
            raise ModelRoutingError("model name is required")
        if self.provider not in {"ollama", "compatible"}:
            raise ModelRoutingError("unsupported model provider")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ModelRoutingError("model priority must be an integer")
        if self.priority < 0 or self.priority > 10_000:
            raise ModelRoutingError("model priority is out of range")
        if self.latency_ms is not None:
            if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int) or self.latency_ms < 0:
                raise ModelRoutingError("model latency must be a non-negative integer")
        if isinstance(self.cost_weight, bool) or not isinstance(self.cost_weight, (int, float)) or self.cost_weight < 0:
            raise ModelRoutingError("model cost weight must be non-negative")


@dataclass(frozen=True)
class RoutingRequest:
    required_capabilities: frozenset[ModelCapability] = field(default_factory=lambda: frozenset({ModelCapability.CHAT}))
    prefer_local: bool = True
    allow_remote: bool = False
    requested_model: str = ""
    fallback_model: str = ""


@dataclass(frozen=True)
class RoutingDecision:
    selected: ModelCandidate
    fallbacks: tuple[ModelCandidate, ...]
    reason: str

    @property
    def chain(self) -> tuple[ModelCandidate, ...]:
        return (self.selected, *self.fallbacks)


class ModelRoutingPolicy:
    """Deterministic, local-first routing over already-discovered model candidates.

    This policy is transport-independent. It does not call model providers and does
    not bypass ModelGateway endpoint, vault, or external-network controls.
    """

    def __init__(self, *, max_fallbacks: int = 3) -> None:
        if isinstance(max_fallbacks, bool) or not isinstance(max_fallbacks, int) or not 0 <= max_fallbacks <= 8:
            raise ModelRoutingError("max fallbacks must be between 0 and 8")
        self.max_fallbacks = max_fallbacks

    @staticmethod
    def _eligible(candidate: ModelCandidate, request: RoutingRequest) -> bool:
        candidate.validate()
        if not candidate.healthy:
            return False
        if candidate.provider_class == ProviderClass.REMOTE and not request.allow_remote:
            return False
        return request.required_capabilities.issubset(candidate.capabilities)

    @staticmethod
    def _score(candidate: ModelCandidate, request: RoutingRequest) -> tuple[int, int, float, int, str]:
        local_penalty = 0 if (request.prefer_local and candidate.provider_class == ProviderClass.LOCAL) else 1
        latency = candidate.latency_ms if candidate.latency_ms is not None else 1_000_000
        return (local_penalty, candidate.priority, float(candidate.cost_weight), latency, candidate.name.lower())

    def decide(self, candidates: Iterable[ModelCandidate], request: RoutingRequest) -> RoutingDecision:
        if not request.required_capabilities:
            raise ModelRoutingError("at least one required capability is required")
        discovered = list(candidates)
        if not discovered:
            raise ModelRoutingError("no model candidates were discovered")

        requested = request.requested_model.strip()
        fallback = request.fallback_model.strip()
        eligible = [candidate for candidate in discovered if self._eligible(candidate, request)]
        if not eligible:
            raise ModelRoutingError("no healthy model satisfies the requested capabilities")

        if requested:
            explicit = next((candidate for candidate in eligible if candidate.name == requested), None)
            if explicit is None:
                raise ModelRoutingError("requested model is unavailable or lacks required capabilities")
            ordered = [explicit, *sorted((item for item in eligible if item.name != explicit.name), key=lambda item: self._score(item, request))]
            reason = "explicit model selected"
        else:
            ordered = sorted(eligible, key=lambda item: self._score(item, request))
            reason = "local-first capability routing"

        if fallback:
            explicit_fallback = next((candidate for candidate in eligible if candidate.name == fallback and candidate.name != ordered[0].name), None)
            if explicit_fallback is not None:
                ordered = [ordered[0], explicit_fallback, *[item for item in ordered[1:] if item.name != explicit_fallback.name]]

        return RoutingDecision(ordered[0], tuple(ordered[1 : 1 + self.max_fallbacks]), reason)

    @staticmethod
    def next_after_failure(decision: RoutingDecision, failed_models: Sequence[str]) -> ModelCandidate | None:
        failed = {str(item).strip() for item in failed_models if str(item).strip()}
        for candidate in decision.chain:
            if candidate.name not in failed:
                return candidate
        return None


__all__ = [
    "ModelCandidate",
    "ModelCapability",
    "ModelRoutingError",
    "ModelRoutingPolicy",
    "ProviderClass",
    "RoutingDecision",
    "RoutingRequest",
]
