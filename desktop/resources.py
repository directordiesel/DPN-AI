"""DPN AI v8 desktop resource and model lifecycle controls.

The controller is provider-agnostic: it decides when a model may remain resident,
when pressure requires eviction, and what evidence should be exposed to the desktop
shell. Provider-specific load/unload calls stay in the existing model gateway.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import psutil


class ResourceState(str, Enum):
    NORMAL = "normal"
    PRESSURE = "pressure"
    CRITICAL = "critical"


class ModelState(str, Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    EVICTING = "evicting"
    FAILED = "failed"


@dataclass(frozen=True)
class ResourcePolicy:
    max_memory_percent: float = 82.0
    critical_memory_percent: float = 92.0
    max_cpu_percent: float = 90.0
    idle_evict_seconds: float = 15 * 60
    minimum_available_memory_mb: int = 1024

    def validate(self) -> None:
        if not 1 <= self.max_memory_percent < self.critical_memory_percent <= 100:
            raise ValueError("memory thresholds must satisfy 1 <= max < critical <= 100")
        if not 1 <= self.max_cpu_percent <= 100:
            raise ValueError("max_cpu_percent must be between 1 and 100")
        if self.idle_evict_seconds < 0:
            raise ValueError("idle_evict_seconds may not be negative")
        if self.minimum_available_memory_mb < 0:
            raise ValueError("minimum_available_memory_mb may not be negative")


@dataclass(frozen=True)
class ResourceSnapshot:
    memory_percent: float
    available_memory_mb: int
    cpu_percent: float
    state: ResourceState


@dataclass
class ModelResidency:
    model: str | None = None
    state: ModelState = ModelState.UNLOADED
    loaded_at: float | None = None
    last_used_at: float | None = None
    failure: str | None = None


class DesktopResourceController:
    """Bound model residency and background work to real machine capacity."""

    def __init__(
        self,
        policy: ResourcePolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        memory_probe: Callable[[], object] = psutil.virtual_memory,
        cpu_probe: Callable[[], float] = lambda: psutil.cpu_percent(interval=None),
    ) -> None:
        self.policy = policy or ResourcePolicy()
        self.policy.validate()
        self._clock = clock
        self._memory_probe = memory_probe
        self._cpu_probe = cpu_probe
        self.residency = ModelResidency()

    def sample(self) -> ResourceSnapshot:
        memory = self._memory_probe()
        memory_percent = float(getattr(memory, "percent"))
        available_mb = int(getattr(memory, "available")) // (1024 * 1024)
        cpu_percent = max(0.0, min(100.0, float(self._cpu_probe())))

        state = ResourceState.NORMAL
        if (
            memory_percent >= self.policy.critical_memory_percent
            or available_mb < self.policy.minimum_available_memory_mb
        ):
            state = ResourceState.CRITICAL
        elif memory_percent >= self.policy.max_memory_percent or cpu_percent >= self.policy.max_cpu_percent:
            state = ResourceState.PRESSURE

        return ResourceSnapshot(
            memory_percent=memory_percent,
            available_memory_mb=available_mb,
            cpu_percent=cpu_percent,
            state=state,
        )

    def can_start_heavy_work(self) -> tuple[bool, str]:
        snapshot = self.sample()
        if snapshot.state is ResourceState.CRITICAL:
            return False, "critical resource pressure"
        if snapshot.state is ResourceState.PRESSURE:
            return False, "resource pressure"
        return True, "capacity available"

    def begin_model_load(self, model: str) -> None:
        model = model.strip()
        if not model:
            raise ValueError("model is required")
        allowed, reason = self.can_start_heavy_work()
        if not allowed:
            raise RuntimeError(f"model load blocked: {reason}")
        self.residency = ModelResidency(model=model, state=ModelState.LOADING)

    def mark_model_ready(self, model: str) -> None:
        if self.residency.state is not ModelState.LOADING or self.residency.model != model:
            raise RuntimeError("model readiness does not match an active load")
        now = self._clock()
        self.residency.state = ModelState.READY
        self.residency.loaded_at = now
        self.residency.last_used_at = now
        self.residency.failure = None

    def mark_model_used(self) -> None:
        if self.residency.state is ModelState.READY:
            self.residency.last_used_at = self._clock()

    def mark_model_failed(self, error: str) -> None:
        self.residency.state = ModelState.FAILED
        self.residency.failure = str(error)[:1000]

    def should_evict(self) -> tuple[bool, str]:
        if self.residency.state is not ModelState.READY:
            return False, "model not resident"
        snapshot = self.sample()
        if snapshot.state is ResourceState.CRITICAL:
            return True, "critical resource pressure"
        if self.residency.last_used_at is not None:
            idle = self._clock() - self.residency.last_used_at
            if idle >= self.policy.idle_evict_seconds:
                return True, "idle residency budget exceeded"
        return False, "residency retained"

    def begin_evict(self) -> None:
        if self.residency.state is not ModelState.READY:
            raise RuntimeError("only a ready model may be evicted")
        self.residency.state = ModelState.EVICTING

    def mark_unloaded(self) -> None:
        self.residency = ModelResidency()

    def summary(self) -> dict[str, object]:
        resources = self.sample()
        return {
            "resources": {
                "state": resources.state.value,
                "memory_percent": round(resources.memory_percent, 1),
                "available_memory_mb": resources.available_memory_mb,
                "cpu_percent": round(resources.cpu_percent, 1),
            },
            "model": {
                "name": self.residency.model,
                "state": self.residency.state.value,
                "loaded": self.residency.state is ModelState.READY,
                "failure": self.residency.failure,
            },
        }
