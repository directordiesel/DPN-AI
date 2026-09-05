from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.performance_recovery_v9 import AdmissionDecision, PerformanceRecoveryPolicy, ResourceSnapshot, UpdateReadiness


@dataclass(frozen=True)
class RuntimeWorkload:
    active_jobs: int = 0
    active_missions: int = 0
    heavy: bool = False
    background: bool = False
    destructive: bool = False

    def validate(self) -> None:
        for name, value in (("active_jobs", self.active_jobs), ("active_missions", self.active_missions)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


class PerformanceRecoveryRuntime:
    """Adapt existing diagnostics/recovery/update evidence to the v9 policy layer."""

    def __init__(self, policy: PerformanceRecoveryPolicy | None = None) -> None:
        self.policy = policy or PerformanceRecoveryPolicy()

    @staticmethod
    def resource_snapshot_from_diagnostics(report: dict[str, Any]) -> ResourceSnapshot:
        cpu = report.get("cpu") or {}
        memory = report.get("memory") or {}
        disk = report.get("disk") or {}
        cpu_percent = float(cpu.get("percent") or 0.0)
        memory_percent = float(memory.get("percent_used") or 0.0)
        total = int(disk.get("total_bytes") or 0)
        free = int(disk.get("free_bytes") or 0)
        if total <= 0 or free < 0 or free > total:
            raise ValueError("diagnostic disk totals are invalid")
        disk_free_percent = (free / total) * 100.0
        snapshot = ResourceSnapshot(cpu_percent, memory_percent, disk_free_percent)
        snapshot.validate()
        return snapshot

    def admission_from_diagnostics(self, report: dict[str, Any], workload: RuntimeWorkload) -> AdmissionDecision:
        workload.validate()
        snapshot = self.resource_snapshot_from_diagnostics(report)
        return self.policy.admit(
            snapshot,
            heavy=workload.heavy,
            background=workload.background,
            destructive=workload.destructive,
        )

    def update_readiness_from_evidence(
        self,
        *,
        manifest_verified: bool,
        artifact_verified: bool,
        rollback_backup_exists: bool,
        workload: RuntimeWorkload,
    ) -> UpdateReadiness:
        workload.validate()
        return self.policy.update_readiness(
            manifest_verified=manifest_verified,
            artifact_verified=artifact_verified,
            rollback_backup_exists=rollback_backup_exists,
            active_jobs=workload.active_jobs,
            active_missions=workload.active_missions,
        )


__all__ = ["PerformanceRecoveryRuntime", "RuntimeWorkload"]
