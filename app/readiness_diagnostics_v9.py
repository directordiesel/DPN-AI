from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from app.capability_readiness_v9 import CapabilityReadiness, CapabilityRegistry


MAX_DIAGNOSTIC_CAPABILITIES = 256


@dataclass(frozen=True)
class ReadinessBlocker:
    capability: str
    stage: str
    reason: str


@dataclass(frozen=True)
class ReadinessDiagnostics:
    total: int
    live: int
    blocked: int
    rc_ready: bool
    blockers: tuple[ReadinessBlocker, ...]

    def payload(self) -> dict[str, object]:
        return asdict(self)


def _blocker_for(item: CapabilityReadiness) -> ReadinessBlocker | None:
    if item.live:
        return None
    if not item.implemented:
        stage = "implementation"
    elif not item.configured:
        stage = "configuration"
    elif not item.permission_enabled:
        stage = "permission"
    else:
        stage = "verification"
    return ReadinessBlocker(capability=item.name, stage=stage, reason=item.reason)


def summarize_readiness(
    registry: CapabilityRegistry,
    *,
    required_capabilities: Iterable[str] = (),
) -> ReadinessDiagnostics:
    if not isinstance(registry, CapabilityRegistry):
        raise TypeError("registry must be a CapabilityRegistry")
    capabilities = tuple(registry.capabilities)
    if len(capabilities) > MAX_DIAGNOSTIC_CAPABILITIES:
        raise ValueError("capability registry exceeds diagnostics limit")

    by_name: dict[str, CapabilityReadiness] = {}
    for item in capabilities:
        if not isinstance(item, CapabilityReadiness):
            raise TypeError("registry contains an invalid capability entry")
        if item.name in by_name:
            raise ValueError(f"duplicate capability in registry: {item.name}")
        by_name[item.name] = item

    required = tuple(dict.fromkeys(str(name).strip() for name in required_capabilities if str(name).strip()))
    unknown = tuple(name for name in required if name not in by_name)
    if unknown:
        raise ValueError(f"unknown required capability: {unknown[0]}")

    selected = tuple(by_name[name] for name in required) if required else capabilities
    blockers = tuple(blocker for item in selected if (blocker := _blocker_for(item)) is not None)
    live = sum(item.live for item in selected)
    return ReadinessDiagnostics(
        total=len(selected),
        live=live,
        blocked=len(blockers),
        rc_ready=not blockers,
        blockers=blockers,
    )


__all__ = [
    "MAX_DIAGNOSTIC_CAPABILITIES",
    "ReadinessBlocker",
    "ReadinessDiagnostics",
    "summarize_readiness",
]
