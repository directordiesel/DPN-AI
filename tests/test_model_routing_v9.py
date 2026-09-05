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
