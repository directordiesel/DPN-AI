import pytest

from app.performance_recovery_runtime_v9 import PerformanceRecoveryRuntime, RuntimeWorkload
from app.performance_recovery_v9 import PressureLevel


def diagnostics(cpu=25.0, memory=35.0, total=1000, free=500):
    return {
        "cpu": {"percent": cpu},
        "memory": {"percent_used": memory},
        "disk": {"total_bytes": total, "free_bytes": free},
    }


def test_diagnostics_are_converted_to_resource_snapshot():
    runtime = PerformanceRecoveryRuntime()
    snapshot = runtime.resource_snapshot_from_diagnostics(diagnostics(cpu=50, memory=60, total=200, free=50))
    assert snapshot.cpu_percent == 50.0
    assert snapshot.memory_percent == 60.0
    assert snapshot.disk_free_percent == 25.0


def test_diagnostics_drive_high_pressure_admission():
    runtime = PerformanceRecoveryRuntime()
    decision = runtime.admission_from_diagnostics(
        diagnostics(cpu=95, memory=50, total=100, free=50),
        RuntimeWorkload(heavy=True, background=True),
    )
    assert decision.allowed is False
    assert decision.pressure == PressureLevel.HIGH


def test_invalid_disk_diagnostics_fail_closed():
    runtime = PerformanceRecoveryRuntime()
    with pytest.raises(ValueError):
        runtime.resource_snapshot_from_diagnostics(diagnostics(total=0, free=0))
    with pytest.raises(ValueError):
        runtime.resource_snapshot_from_diagnostics(diagnostics(total=100, free=101))


def test_update_readiness_uses_active_workload_counts():
    runtime = PerformanceRecoveryRuntime()
    blocked = runtime.update_readiness_from_evidence(
        manifest_verified=True,
        artifact_verified=True,
        rollback_backup_exists=True,
        workload=RuntimeWorkload(active_jobs=0, active_missions=1),
    )
    assert blocked.ready is False
    ready = runtime.update_readiness_from_evidence(
        manifest_verified=True,
        artifact_verified=True,
        rollback_backup_exists=True,
        workload=RuntimeWorkload(active_jobs=0, active_missions=0),
    )
    assert ready.ready is True


def test_workload_counts_reject_boolean_and_negative_values():
    with pytest.raises(ValueError):
        RuntimeWorkload(active_jobs=True).validate()
    with pytest.raises(ValueError):
        RuntimeWorkload(active_missions=-1).validate()
