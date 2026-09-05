from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PressureLevel(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_percent: float
    memory_percent: float
    disk_free_percent: float

    def validate(self) -> None:
        for name, value in (
            ("cpu_percent", self.cpu_percent),
            ("memory_percent", self.memory_percent),
            ("disk_free_percent", self.disk_free_percent),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not 0 <= float(value) <= 100:
                raise ValueError(f"{name} must be between 0 and 100")


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    pressure: PressureLevel
    capability_state: CapabilityState
    reason: str
    max_parallelism: int
    should_cancel_background: bool


@dataclass(frozen=True)
class RecoveryDecision:
    restore_allowed: bool
    require_snapshot_verification: bool
    require_pre_restore_backup: bool
    reason: str


@dataclass(frozen=True)
class UpdateReadiness:
    ready: bool
    require_verified_manifest: bool
    require_verified_artifact: bool
    require_rollback_backup: bool
    require_idle_runtime: bool
    reason: str


class PerformanceRecoveryPolicy:
    """Deterministic v9 runtime-pressure, recovery, and update readiness policy."""

    def __init__(
        self,
        *,
        elevated_cpu: float = 75.0,
        high_cpu: float = 90.0,
        elevated_memory: float = 80.0,
        high_memory: float = 92.0,
        minimum_disk_free_percent: float = 8.0,
        critical_disk_free_percent: float = 3.0,
    ) -> None:
        self.elevated_cpu = float(elevated_cpu)
        self.high_cpu = float(high_cpu)
        self.elevated_memory = float(elevated_memory)
        self.high_memory = float(high_memory)
        self.minimum_disk_free_percent = float(minimum_disk_free_percent)
        self.critical_disk_free_percent = float(critical_disk_free_percent)
        if not 0 <= self.elevated_cpu < self.high_cpu <= 100:
            raise ValueError("invalid CPU pressure thresholds")
        if not 0 <= self.elevated_memory < self.high_memory <= 100:
            raise ValueError("invalid memory pressure thresholds")
        if not 0 <= self.critical_disk_free_percent < self.minimum_disk_free_percent <= 100:
            raise ValueError("invalid disk pressure thresholds")

    def pressure(self, snapshot: ResourceSnapshot) -> PressureLevel:
        snapshot.validate()
        if snapshot.disk_free_percent <= self.critical_disk_free_percent:
            return PressureLevel.CRITICAL
        if snapshot.cpu_percent >= self.high_cpu or snapshot.memory_percent >= self.high_memory:
            return PressureLevel.HIGH
        if snapshot.disk_free_percent <= self.minimum_disk_free_percent:
            return PressureLevel.HIGH
        if snapshot.cpu_percent >= self.elevated_cpu or snapshot.memory_percent >= self.elevated_memory:
            return PressureLevel.ELEVATED
        return PressureLevel.NORMAL

    def admit(
        self,
        snapshot: ResourceSnapshot,
        *,
        heavy: bool = False,
        background: bool = False,
        destructive: bool = False,
    ) -> AdmissionDecision:
        level = self.pressure(snapshot)
        if level == PressureLevel.CRITICAL:
            return AdmissionDecision(False, level, CapabilityState.BLOCKED, "critical resource pressure", 0, True)
        if level == PressureLevel.HIGH:
            if heavy or background:
                return AdmissionDecision(False, level, CapabilityState.DEGRADED, "heavy/background work blocked under high pressure", 1, True)
            return AdmissionDecision(True, level, CapabilityState.DEGRADED, "foreground light work allowed under high pressure", 1, True)
        if level == PressureLevel.ELEVATED:
            parallelism = 1 if heavy else 2
            return AdmissionDecision(True, level, CapabilityState.DEGRADED, "reduced parallelism under elevated pressure", parallelism, background)
        return AdmissionDecision(True, level, CapabilityState.AVAILABLE, "resources healthy", 4 if not destructive else 1, False)

    @staticmethod
    def recovery_decision(
        *,
        snapshot_exists: bool,
        snapshot_verified: bool,
        pre_restore_backup_exists: bool,
        overwrite: bool,
    ) -> RecoveryDecision:
        if not snapshot_exists:
            return RecoveryDecision(False, True, True, "snapshot is missing")
        if not snapshot_verified:
            return RecoveryDecision(False, True, True, "snapshot integrity must verify before restore")
        if overwrite and not pre_restore_backup_exists:
            return RecoveryDecision(False, True, True, "overwrite restore requires a pre-restore backup")
        return RecoveryDecision(True, True, overwrite, "restore prerequisites satisfied")

    @staticmethod
    def update_readiness(
        *,
        manifest_verified: bool,
        artifact_verified: bool,
        rollback_backup_exists: bool,
        active_jobs: int,
        active_missions: int,
    ) -> UpdateReadiness:
        if isinstance(active_jobs, bool) or not isinstance(active_jobs, int) or active_jobs < 0:
            raise ValueError("active_jobs must be a non-negative integer")
        if isinstance(active_missions, bool) or not isinstance(active_missions, int) or active_missions < 0:
            raise ValueError("active_missions must be a non-negative integer")
        if not manifest_verified:
            return UpdateReadiness(False, True, True, True, True, "signed update manifest is not verified")
        if not artifact_verified:
            return UpdateReadiness(False, True, True, True, True, "update artifact integrity is not verified")
        if not rollback_backup_exists:
            return UpdateReadiness(False, True, True, True, True, "verified rollback backup is required")
        if active_jobs or active_missions:
            return UpdateReadiness(False, True, True, True, True, "runtime must be idle before activation")
        return UpdateReadiness(True, True, True, True, True, "update is ready to stage")


__all__ = [
    "AdmissionDecision",
    "CapabilityState",
    "PerformanceRecoveryPolicy",
    "PressureLevel",
    "RecoveryDecision",
    "ResourceSnapshot",
    "UpdateReadiness",
]
