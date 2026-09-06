import math

import pytest

from app.model_discovery_v9 import (
    BenchmarkEvidence,
    DiscoveredModel,
    MAX_BENCHMARK_SAMPLES,
    MAX_DISCOVERED_MODELS,
    ModelDiscoveryError,
    candidate_from_evidence,
    validate_benchmark,
    validate_discovery,
)
from app.model_routing_v9 import ModelCapability, ProviderClass


def _local(name: str = "qwen2.5:7b") -> DiscoveredModel:
    return DiscoveredModel(
        name=name,
        provider="ollama",
        provider_class=ProviderClass.LOCAL,
        capabilities=frozenset({ModelCapability.CHAT, ModelCapability.CODE}),
        evidence="ollama inventory response",
    )


def test_discovery_requires_explicit_bounded_evidence_and_capabilities():
    assert validate_discovery((_local(),))[0].name == "qwen2.5:7b"
    with pytest.raises(ModelDiscoveryError, match="evidence"):
        validate_discovery((DiscoveredModel("qwen2.5:7b", "ollama", ProviderClass.LOCAL, frozenset({ModelCapability.CHAT}), ""),))
    with pytest.raises(ModelDiscoveryError, match="capabilities"):
        validate_discovery((DiscoveredModel("qwen2.5:7b", "ollama", ProviderClass.LOCAL, frozenset(), "inventory"),))


def test_discovery_rejects_duplicates_and_inventory_overflow():
    with pytest.raises(ModelDiscoveryError, match="duplicate"):
        validate_discovery((_local(), _local("QWEN2.5:7B")))
    with pytest.raises(ModelDiscoveryError, match="count"):
        validate_discovery(tuple(_local(f"model-{i}") for i in range(MAX_DISCOVERED_MODELS + 1)))


def test_benchmark_validation_is_finite_bounded_and_consistent():
    valid = BenchmarkEvidence("qwen2.5:7b", samples=10, passed=9, latency_ms=25, quality_score=0.9, health_score=0.95)
    assert validate_benchmark(valid) == valid
    for bad in (math.nan, math.inf, -0.1, 1.1):
        with pytest.raises(ModelDiscoveryError):
            validate_benchmark(BenchmarkEvidence("qwen2.5:7b", 1, 1, quality_score=bad))
    with pytest.raises(ModelDiscoveryError, match="samples"):
        validate_benchmark(BenchmarkEvidence("qwen2.5:7b", MAX_BENCHMARK_SAMPLES + 1, 1))
    with pytest.raises(ModelDiscoveryError, match="passed"):
        validate_benchmark(BenchmarkEvidence("qwen2.5:7b", 2, 3))


def test_candidate_without_benchmark_evidence_fails_closed_as_unhealthy():
    candidate = candidate_from_evidence(_local())
    assert candidate.healthy is False
    assert candidate.health_score == 0.0
    assert candidate.quality_score == 0.0
    assert candidate.latency_ms is None


def test_candidate_uses_only_supplied_benchmark_evidence():
    evidence = BenchmarkEvidence("qwen2.5:7b", samples=4, passed=3, latency_ms=42)
    candidate = candidate_from_evidence(_local(), evidence)
    assert candidate.healthy is True
    assert candidate.health_score == 0.75
    assert candidate.quality_score == 0.75
    assert candidate.latency_ms == 42
    assert candidate.provider_class is ProviderClass.LOCAL


def test_benchmark_cannot_be_applied_to_different_model():
    with pytest.raises(ModelDiscoveryError, match="different model"):
        candidate_from_evidence(_local(), BenchmarkEvidence("other-model", samples=1, passed=1))
