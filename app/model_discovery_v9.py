from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from app.model_routing_v9 import ModelCandidate, ModelCapability, ModelRoutingError, ProviderClass


MAX_DISCOVERED_MODELS = 256
MAX_BENCHMARK_SAMPLES = 1000
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,191}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class DiscoveredModel:
    name: str
    provider: str
    provider_class: ProviderClass
    capabilities: frozenset[ModelCapability]
    evidence: str


@dataclass(frozen=True)
class BenchmarkEvidence:
    model: str
    provider: str
    samples: int
    passed: int
    latency_ms: int | None = None
    quality_score: float | None = None
    health_score: float | None = None


class ModelDiscoveryError(ModelRoutingError):
    """Raised when model discovery or benchmark evidence is malformed."""


def validate_discovery(models: Iterable[DiscoveredModel]) -> tuple[DiscoveredModel, ...]:
    values = tuple(models)
    if len(values) > MAX_DISCOVERED_MODELS:
        raise ModelDiscoveryError("discovered model count exceeds configured limit")

    seen: set[tuple[str, str]] = set()
    normalized: list[DiscoveredModel] = []
    for model in values:
        if not isinstance(model, DiscoveredModel):
            raise ModelDiscoveryError("discovery entries must be DiscoveredModel values")
        name = str(model.name or "").strip()
        provider = str(model.provider or "").strip().lower()
        evidence = str(model.evidence or "").strip()
        if not _MODEL_NAME_RE.fullmatch(name):
            raise ModelDiscoveryError("discovered model name is invalid")
        if not _PROVIDER_RE.fullmatch(provider):
            raise ModelDiscoveryError("discovered provider identifier is invalid")
        if not isinstance(model.provider_class, ProviderClass):
            raise ModelDiscoveryError("provider_class must be ProviderClass")
        if not model.capabilities:
            raise ModelDiscoveryError("discovered model must include explicit capabilities")
        if any(not isinstance(capability, ModelCapability) for capability in model.capabilities):
            raise ModelDiscoveryError("discovered model capability is invalid")
        if not evidence or len(evidence) > 512:
            raise ModelDiscoveryError("discovery evidence is required and must be bounded")
        key = (provider, name.lower())
        if key in seen:
            raise ModelDiscoveryError("duplicate discovered model")
        seen.add(key)
        normalized.append(
            DiscoveredModel(
                name=name,
                provider=provider,
                provider_class=model.provider_class,
                capabilities=frozenset(model.capabilities),
                evidence=evidence,
            )
        )
    return tuple(normalized)


def validate_benchmark(evidence: BenchmarkEvidence) -> BenchmarkEvidence:
    if not isinstance(evidence, BenchmarkEvidence):
        raise ModelDiscoveryError("benchmark evidence must be BenchmarkEvidence")
    model = str(evidence.model or "").strip()
    provider = str(evidence.provider or "").strip().lower()
    if not _MODEL_NAME_RE.fullmatch(model):
        raise ModelDiscoveryError("benchmark model name is invalid")
    if not _PROVIDER_RE.fullmatch(provider):
        raise ModelDiscoveryError("benchmark provider identifier is invalid")
    for value, field_name in ((evidence.samples, "samples"), (evidence.passed, "passed")):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ModelDiscoveryError(f"benchmark {field_name} must be an integer")
    if not 1 <= evidence.samples <= MAX_BENCHMARK_SAMPLES:
        raise ModelDiscoveryError("benchmark samples are out of range")
    if not 0 <= evidence.passed <= evidence.samples:
        raise ModelDiscoveryError("benchmark passed count is out of range")
    if evidence.latency_ms is not None:
        if isinstance(evidence.latency_ms, bool) or not isinstance(evidence.latency_ms, int) or evidence.latency_ms < 0:
            raise ModelDiscoveryError("benchmark latency must be a non-negative integer")
    for value, field_name in ((evidence.quality_score, "quality score"), (evidence.health_score, "health score")):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ModelDiscoveryError(f"benchmark {field_name} must be between 0 and 1")
    return BenchmarkEvidence(
        model=model,
        provider=provider,
        samples=evidence.samples,
        passed=evidence.passed,
        latency_ms=evidence.latency_ms,
        quality_score=evidence.quality_score,
        health_score=evidence.health_score,
    )


def candidate_from_evidence(
    discovered: DiscoveredModel,
    benchmark: BenchmarkEvidence | None = None,
    *,
    priority: int = 100,
    cost_weight: float = 0.0,
) -> ModelCandidate:
    model = validate_discovery((discovered,))[0]
    quality = 0.0
    health = 0.0
    latency = None
    healthy = False

    if benchmark is not None:
        result = validate_benchmark(benchmark)
        if result.provider != model.provider or result.model != model.name:
            raise ModelDiscoveryError("benchmark evidence belongs to a different provider/model identity")
        quality = float(result.quality_score) if result.quality_score is not None else (result.passed / result.samples)
        health = float(result.health_score) if result.health_score is not None else (result.passed / result.samples)
        latency = result.latency_ms
        healthy = result.passed > 0 and health > 0.0

    candidate = ModelCandidate(
        name=model.name,
        provider=model.provider,
        provider_class=model.provider_class,
        capabilities=model.capabilities,
        healthy=healthy,
        priority=priority,
        latency_ms=latency,
        cost_weight=cost_weight,
        health_score=health,
        quality_score=quality,
    )
    candidate.validate()
    return candidate


__all__ = [
    "BenchmarkEvidence",
    "DiscoveredModel",
    "MAX_BENCHMARK_SAMPLES",
    "MAX_DISCOVERED_MODELS",
    "ModelDiscoveryError",
    "candidate_from_evidence",
    "validate_benchmark",
    "validate_discovery",
]
