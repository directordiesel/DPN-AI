from __future__ import annotations

import pytest

from app.model_intelligence_v10 import (
    BenchmarkProfile,
    IntelligenceRequest,
    ModelIntelligenceEngine,
    PrivacyMode,
    TaskDifficulty,
)
from app.model_routing_v9 import ModelCandidate, ModelCapability, ModelRoutingError, ProviderClass


def candidate(
    name: str,
    *,
    provider_class: ProviderClass = ProviderClass.LOCAL,
    capabilities: frozenset[ModelCapability] = frozenset({ModelCapability.CHAT, ModelCapability.REASONING}),
    latency_ms: int | None = 500,
    cost_weight: float = 0.0,
    health_score: float = 1.0,
    quality_score: float = 0.8,
) -> ModelCandidate:
    return ModelCandidate(
        name=name,
        provider="ollama" if provider_class == ProviderClass.LOCAL else "compatible",
        provider_class=provider_class,
        capabilities=capabilities,
        latency_ms=latency_ms,
        cost_weight=cost_weight,
        health_score=health_score,
        quality_score=quality_score,
    )


def benchmark(
    name: str,
    *,
    success_rate: float,
    samples: int = 100,
    task_family: str = "reasoning",
    quality_score: float | None = 0.8,
    median_latency_ms: int | None = 500,
) -> BenchmarkProfile:
    return BenchmarkProfile(
        model_name=name,
        task_family=task_family,
        success_rate=success_rate,
        sample_count=samples,
        quality_score=quality_score,
        median_latency_ms=median_latency_ms,
    )


def test_selects_stronger_benchmark_for_hard_reasoning() -> None:
    engine = ModelIntelligenceEngine()
    decision = engine.decide(
        [candidate("small"), candidate("large")],
        [benchmark("small", success_rate=0.71), benchmark("large", success_rate=0.95)],
        IntelligenceRequest(task_family="reasoning", difficulty=TaskDifficulty.HIGH),
    )
    assert decision.selected.name == "large"
    assert decision.benchmark.success_rate == pytest.approx(0.95)
    assert "benchmark-backed" in decision.reason


def test_local_only_fails_closed_when_only_remote_model_qualifies() -> None:
    engine = ModelIntelligenceEngine()
    with pytest.raises(ModelRoutingError, match="no model satisfies"):
        engine.decide(
            [candidate("remote", provider_class=ProviderClass.REMOTE)],
            [benchmark("remote", success_rate=0.99)],
            IntelligenceRequest(task_family="reasoning", privacy_mode=PrivacyMode.LOCAL_ONLY),
        )


def test_requires_matching_benchmark_evidence() -> None:
    engine = ModelIntelligenceEngine()
    with pytest.raises(ModelRoutingError, match="no model satisfies"):
        engine.decide(
            [candidate("local")],
            [benchmark("local", success_rate=0.99, task_family="code")],
            IntelligenceRequest(task_family="reasoning"),
        )


def test_enforces_minimum_benchmark_samples_and_success_rate() -> None:
    engine = ModelIntelligenceEngine()
    with pytest.raises(ModelRoutingError, match="no model satisfies"):
        engine.decide(
            [candidate("local")],
            [benchmark("local", success_rate=0.80, samples=5)],
            IntelligenceRequest(
                task_family="reasoning",
                minimum_samples=20,
                minimum_success_rate=0.85,
            ),
        )


def test_capability_requirement_is_enforced() -> None:
    engine = ModelIntelligenceEngine()
    with pytest.raises(ModelRoutingError, match="no model satisfies"):
        engine.decide(
            [candidate("chat-only", capabilities=frozenset({ModelCapability.CHAT}))],
            [benchmark("chat-only", success_rate=0.99)],
            IntelligenceRequest(
                task_family="reasoning",
                required_capabilities=frozenset({ModelCapability.CHAT, ModelCapability.REASONING}),
            ),
        )


def test_latency_and_cost_budgets_filter_candidates() -> None:
    engine = ModelIntelligenceEngine()
    decision = engine.decide(
        [
            candidate("fast", latency_ms=100, cost_weight=0.1),
            candidate("slow", latency_ms=5_000, cost_weight=5.0),
        ],
        [benchmark("fast", success_rate=0.90), benchmark("slow", success_rate=0.99)],
        IntelligenceRequest(
            task_family="reasoning",
            max_latency_ms=1_000,
            max_cost_weight=1.0,
        ),
    )
    assert decision.selected.name == "fast"


def test_prefers_larger_sample_record_for_same_model_and_task_family() -> None:
    engine = ModelIntelligenceEngine()
    decision = engine.decide(
        [candidate("local")],
        [
            benchmark("local", success_rate=0.50, samples=10),
            benchmark("local", success_rate=0.92, samples=100),
        ],
        IntelligenceRequest(task_family="reasoning", minimum_samples=20),
    )
    assert decision.benchmark.sample_count == 100
    assert decision.benchmark.success_rate == pytest.approx(0.92)


def test_invalid_benchmark_is_rejected() -> None:
    engine = ModelIntelligenceEngine()
    with pytest.raises(ModelRoutingError, match="success rate"):
        engine.decide(
            [candidate("local")],
            [benchmark("local", success_rate=1.5)],
            IntelligenceRequest(task_family="reasoning"),
        )
