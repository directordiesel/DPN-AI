import asyncio

import pytest

from app.model_failover_v9 import ModelFailoverError, ModelFailoverExecutor
from app.model_routing_runtime_v9 import ModelRouteContext


def run(coro):
    return asyncio.run(coro)


def test_local_failure_falls_back_to_next_local_candidate():
    items = [
        {"name": "ollama:coder-a", "model": "coder-a", "provider": "ollama", "healthy": True},
        {"name": "ollama:coder-b", "model": "coder-b", "provider": "ollama", "healthy": True},
    ]
    seen = []

    async def execute(model):
        seen.append(model)
        if model == "ollama:coder-a":
            raise RuntimeError("provider unavailable")
        return {"message": {"content": "ok"}}

    result = run(ModelFailoverExecutor(max_attempts=2).execute(items, ModelRouteContext(profile="software"), execute))
    assert result.selected_model == "ollama:coder-b"
    assert seen == ["ollama:coder-a", "ollama:coder-b"]
    assert [attempt.ok for attempt in result.attempts] == [False, True]


def test_remote_candidate_is_not_used_when_remote_is_disallowed():
    items = [
        {"name": "ollama:local-a", "model": "local-a", "provider": "ollama", "healthy": True},
        {"name": "compatible:remote-a", "model": "remote-a", "provider": "compatible", "healthy": True},
    ]
    seen = []

    async def execute(model):
        seen.append(model)
        raise RuntimeError("down")

    with pytest.raises(ModelFailoverError):
        run(ModelFailoverExecutor(max_attempts=3).execute(items, ModelRouteContext(allow_remote=False), execute))
    assert seen == ["ollama:local-a"]


def test_remote_candidate_can_be_used_only_when_policy_allows_it():
    items = [
        {"name": "ollama:local-a", "model": "local-a", "provider": "ollama", "healthy": True},
        {"name": "compatible:remote-a", "model": "remote-a", "provider": "compatible", "healthy": True},
    ]

    async def execute(model):
        if model == "ollama:local-a":
            raise RuntimeError("local down")
        return {"message": {"content": "remote ok"}}

    result = run(ModelFailoverExecutor(max_attempts=3).execute(items, ModelRouteContext(allow_remote=True), execute))
    assert result.selected_model == "compatible:remote-a"


def test_explicit_model_failure_does_not_repeat_same_candidate():
    items = [
        {"name": "ollama:first", "model": "first", "provider": "ollama", "healthy": True},
        {"name": "ollama:second", "model": "second", "provider": "ollama", "healthy": True},
    ]
    seen = []

    def execute(model):
        seen.append(model)
        if model == "ollama:first":
            raise RuntimeError("first failed")
        return {"ok": True}

    result = run(
        ModelFailoverExecutor(max_attempts=2).execute(
            items,
            ModelRouteContext(requested_model="ollama:first"),
            execute,
        )
    )
    assert result.selected_model == "ollama:second"
    assert seen == ["ollama:first", "ollama:second"]


def test_non_dict_provider_result_fails_closed():
    items = [{"name": "ollama:local-a", "model": "local-a", "provider": "ollama", "healthy": True}]
    with pytest.raises(ModelFailoverError, match="No policy-allowed model"):
        run(ModelFailoverExecutor(max_attempts=1).execute(items, ModelRouteContext(), lambda _: "bad-result"))


def test_invalid_attempt_limit_is_rejected():
    for value in (True, 0, 9, 1.5):
        with pytest.raises(ValueError):
            ModelFailoverExecutor(max_attempts=value)
