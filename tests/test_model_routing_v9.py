import math

import pytest

from app.model_routing_v9 import (
    ModelCandidate,
    ModelCapability,
    ModelRoutingError,
    ModelRoutingPolicy,
    ProviderClass,
    RoutingRequest,
)


def candidate(name: str, provider_class: ProviderClass, *caps: ModelCapability, **kwargs):
    return ModelCandidate(
        name=name,
        provider="ollama" if provider_class == ProviderClass.LOCAL else "compatible",
        provider_class=provider_class,
        capabilities=frozenset(caps),
        **kwargs,
    )


def test_prefers_local_healthy_model_when_capabilities_match():
    policy = ModelRoutingPolicy(max_fallbacks=2)
    decision = policy.decide(
        [
            candidate("remote-fast", ProviderClass.REMOTE, ModelCapability.CHAT, priority=1, latency_ms=20),
            candidate("local-main", ProviderClass.LOCAL, ModelCapability.CHAT, priority=50, latency_ms=200),
        ],
        RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), prefer_local=True, allow_remote=True),
    )
    assert decision.selected.name == "local-main"
    assert decision.fallbacks[0].name == "remote-fast"


def test_remote_models_fail_closed_when_not_allowed():
    policy = ModelRoutingPolicy()
    with pytest.raises(ModelRoutingError, match="no healthy model"):
        policy.decide(
            [candidate("remote-only", ProviderClass.REMOTE, ModelCapability.CHAT)],
            RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), allow_remote=False),
        )


def test_capability_matching_excludes_non_vision_models():
    policy = ModelRoutingPolicy()
    decision = policy.decide(
        [
            candidate("text", ProviderClass.LOCAL, ModelCapability.CHAT),
            candidate("vision", ProviderClass.LOCAL, ModelCapability.CHAT, ModelCapability.VISION),
        ],
        RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT, ModelCapability.VISION})),
    )
    assert decision.selected.name == "vision"


def test_explicit_model_must_still_satisfy_policy():
    policy = ModelRoutingPolicy()
    with pytest.raises(ModelRoutingError, match="requested model"):
        policy.decide(
            [candidate("text", ProviderClass.LOCAL, ModelCapability.CHAT)],
            RoutingRequest(
                required_capabilities=frozenset({ModelCapability.CHAT, ModelCapability.VISION}),
                requested_model="text",
            ),
        )


def test_explicit_fallback_is_promoted_after_selected_model():
    policy = ModelRoutingPolicy(max_fallbacks=3)
    decision = policy.decide(
        [
            candidate("a", ProviderClass.LOCAL, ModelCapability.CHAT, priority=10),
            candidate("b", ProviderClass.LOCAL, ModelCapability.CHAT, priority=20),
            candidate("c", ProviderClass.LOCAL, ModelCapability.CHAT, priority=30),
        ],
        RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), fallback_model="c"),
    )
    assert [item.name for item in decision.chain] == ["a", "c", "b"]


def test_next_after_failure_advances_through_chain():
    policy = ModelRoutingPolicy(max_fallbacks=2)
    decision = policy.decide(
        [
            candidate("a", ProviderClass.LOCAL, ModelCapability.CHAT, priority=10),
            candidate("b", ProviderClass.LOCAL, ModelCapability.CHAT, priority=20),
            candidate("c", ProviderClass.LOCAL, ModelCapability.CHAT, priority=30),
        ],
        RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT})),
    )
    assert policy.next_after_failure(decision, ["a"]).name == "b"
    assert policy.next_after_failure(decision, ["a", "b", "c"]) is None


def test_invalid_boolean_priority_and_latency_are_rejected():
    policy = ModelRoutingPolicy()
    with pytest.raises(ModelRoutingError, match="priority"):
        policy.decide(
            [candidate("bad", ProviderClass.LOCAL, ModelCapability.CHAT, priority=True)],
            RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT})),
        )
    with pytest.raises(ModelRoutingError, match="latency"):
        policy.decide(
            [candidate("bad", ProviderClass.LOCAL, ModelCapability.CHAT, latency_ms=True)],
            RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT})),
        )


def test_health_threshold_and_failure_quarantine_fail_closed():
    policy = ModelRoutingPolicy(quarantine_after_failures=3)
    decision = policy.decide(
        [
            candidate("degraded", ProviderClass.LOCAL, ModelCapability.CHAT, health_score=0.2, priority=1),
            candidate("quarantined", ProviderClass.LOCAL, ModelCapability.CHAT, health_score=1.0, consecutive_failures=3, priority=2),
            candidate("healthy", ProviderClass.LOCAL, ModelCapability.CHAT, health_score=0.9, priority=50),
        ],
        RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), minimum_health_score=0.25),
    )
    assert decision.selected.name == "healthy"
    assert [item.name for item in decision.chain] == ["healthy"]


def test_quality_breaks_equal_priority_ties_without_overriding_local_first():
    policy = ModelRoutingPolicy(max_fallbacks=2)
    decision = policy.decide(
        [
            candidate("local-low", ProviderClass.LOCAL, ModelCapability.CHAT, priority=10, quality_score=0.4),
            candidate("local-high", ProviderClass.LOCAL, ModelCapability.CHAT, priority=10, quality_score=0.9),
            candidate("remote-best", ProviderClass.REMOTE, ModelCapability.CHAT, priority=1, quality_score=1.0),
        ],
        RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), prefer_local=True, allow_remote=True),
    )
    assert decision.selected.name == "local-high"
    assert decision.fallbacks[0].name == "local-low"


def test_minimum_quality_excludes_unqualified_models():
    policy = ModelRoutingPolicy()
    with pytest.raises(ModelRoutingError, match="no healthy model"):
        policy.decide(
            [candidate("weak", ProviderClass.LOCAL, ModelCapability.CODE, quality_score=0.3)],
            RoutingRequest(required_capabilities=frozenset({ModelCapability.CODE}), minimum_quality_score=0.8),
        )


def test_explicit_requested_model_cannot_bypass_health_quarantine():
    policy = ModelRoutingPolicy(quarantine_after_failures=2)
    with pytest.raises(ModelRoutingError, match="requested model"):
        policy.decide(
            [candidate("requested", ProviderClass.LOCAL, ModelCapability.CHAT, consecutive_failures=2)],
            RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), requested_model="requested"),
        )


def test_non_finite_scores_and_invalid_request_thresholds_are_rejected():
    policy = ModelRoutingPolicy()
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ModelRoutingError, match="health score"):
            policy.decide(
                [candidate("bad", ProviderClass.LOCAL, ModelCapability.CHAT, health_score=value)],
                RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT})),
            )
    with pytest.raises(ModelRoutingError, match="minimum health score"):
        policy.decide(
            [candidate("ok", ProviderClass.LOCAL, ModelCapability.CHAT)],
            RoutingRequest(required_capabilities=frozenset({ModelCapability.CHAT}), minimum_health_score=1.1),
        )


def test_invalid_quarantine_threshold_is_rejected():
    with pytest.raises(ModelRoutingError, match="quarantine"):
        ModelRoutingPolicy(quarantine_after_failures=0)
