from types import SimpleNamespace

import pytest

from desktop.resources import (
    DesktopResourceController,
    ModelState,
    ResourcePolicy,
    ResourceState,
)


class Clock:
    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value


def memory(percent: float, available_mb: int):
    return SimpleNamespace(percent=percent, available=available_mb * 1024 * 1024)


def controller(*, memory_percent=40.0, available_mb=8192, cpu=10.0, clock=None, policy=None):
    return DesktopResourceController(
        policy=policy,
        clock=clock or Clock(),
        memory_probe=lambda: memory(memory_percent, available_mb),
        cpu_probe=lambda: cpu,
    )


def test_policy_rejects_inverted_memory_thresholds():
    with pytest.raises(ValueError):
        DesktopResourceController(ResourcePolicy(max_memory_percent=95, critical_memory_percent=90))


def test_resource_sampling_reports_normal_pressure_and_critical():
    assert controller().sample().state is ResourceState.NORMAL
    assert controller(memory_percent=85).sample().state is ResourceState.PRESSURE
    assert controller(memory_percent=95).sample().state is ResourceState.CRITICAL
    assert controller(available_mb=128).sample().state is ResourceState.CRITICAL


def test_heavy_work_is_blocked_under_pressure():
    allowed, reason = controller(memory_percent=85).can_start_heavy_work()
    assert allowed is False
    assert reason == "resource pressure"


def test_model_load_is_fail_closed_under_critical_pressure():
    resource = controller(memory_percent=95)
    with pytest.raises(RuntimeError, match="critical resource pressure"):
        resource.begin_model_load("qwen3")
    assert resource.residency.state is ModelState.UNLOADED


def test_model_lifecycle_tracks_ready_use_and_unload():
    clock = Clock()
    resource = controller(clock=clock)
    resource.begin_model_load("qwen3")
    assert resource.residency.state is ModelState.LOADING

    resource.mark_model_ready("qwen3")
    assert resource.residency.state is ModelState.READY
    assert resource.residency.loaded_at == 100.0

    clock.value = 125.0
    resource.mark_model_used()
    assert resource.residency.last_used_at == 125.0

    resource.begin_evict()
    assert resource.residency.state is ModelState.EVICTING
    resource.mark_unloaded()
    assert resource.residency.state is ModelState.UNLOADED
    assert resource.residency.model is None


def test_readiness_must_match_active_model_load():
    resource = controller()
    resource.begin_model_load("qwen3")
    with pytest.raises(RuntimeError, match="does not match"):
        resource.mark_model_ready("different-model")


def test_idle_model_is_evicted_after_budget():
    clock = Clock()
    resource = controller(
        clock=clock,
        policy=ResourcePolicy(idle_evict_seconds=30, minimum_available_memory_mb=256),
    )
    resource.begin_model_load("qwen3")
    resource.mark_model_ready("qwen3")

    clock.value = 131.0
    should_evict, reason = resource.should_evict()
    assert should_evict is True
    assert reason == "idle residency budget exceeded"


def test_critical_pressure_evicts_resident_model_before_idle_budget():
    clock = Clock()
    memory_state = {"percent": 30.0, "available_mb": 8192}
    resource = DesktopResourceController(
        clock=clock,
        memory_probe=lambda: memory(memory_state["percent"], memory_state["available_mb"]),
        cpu_probe=lambda: 5.0,
    )
    resource.begin_model_load("qwen3")
    resource.mark_model_ready("qwen3")

    memory_state["percent"] = 95.0
    should_evict, reason = resource.should_evict()
    assert should_evict is True
    assert reason == "critical resource pressure"


def test_failure_summary_is_bounded_and_secret_free_shape():
    resource = controller()
    resource.begin_model_load("qwen3")
    resource.mark_model_failed("x" * 2000)
    summary = resource.summary()
    assert summary["model"]["state"] == "failed"
    assert len(summary["model"]["failure"]) == 1000
    assert set(summary["resources"]) == {
        "state",
        "memory_percent",
        "available_memory_mb",
        "cpu_percent",
    }
