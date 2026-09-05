import pytest

from app.performance_recovery_v9 import (
    CapabilityState,
    PerformanceRecoveryPolicy,
    PressureLevel,
    ResourceSnapshot,
)


def test_normal_resources_allow_work():
    policy = PerformanceRecoveryPolicy()
    decision = policy.admit(ResourceSnapshot(20, 30, 60), heavy=True)
    assert decision.allowed is True
    assert decision.pressure == PressureLevel.NORMAL
    assert decision.capability_state == CapabilityState.AVAILABLE


def test_elevated_pressure_reduces_parallelism():
    policy = PerformanceRecoveryPolicy()
    decision = policy.admit(ResourceSnapshot(80, 50, 50), heavy=True)
    assert decision.allowed is True
    assert decision.pressure == PressureLevel.ELEVATED
    assert decision.max_parallelism == 1


def test_high_pressure_blocks_heavy_background_work():
    policy = PerformanceRecoveryPolicy()
    decision = policy.admit(ResourceSnapshot(95, 50, 50), heavy=True, background=True)
    assert decision.allowed is False
    assert decision.pressure == PressureLevel.HIGH
    assert decision.should_cancel_background is True


def test_critical_disk_pressure_fails_closed():
    policy = PerformanceRecoveryPolicy()
    decision = policy.admit(ResourceSnapshot(20, 20, 2))
    assert decision.allowed is False
    assert decision.pressure == PressureLevel.CRITICAL
    assert decision.capability_state == CapabilityState.BLOCKED


def test_restore_requires_verified_snapshot():
    decision = PerformanceRecoveryPolicy.recovery_decision(
        snapshot_exists=True,
        snapshot_verified=False,
        pre_restore_backup_exists=True,
        overwrite=True,
    )
    assert decision.restore_allowed is False
    assert decision.require_snapshot_verification is True


def test_overwrite_restore_requires_pre_restore_backup():
    decision = PerformanceRecoveryPolicy.recovery_decision(
        snapshot_exists=True,
        snapshot_verified=True,
        pre_restore_backup_exists=False,
        overwrite=True,
    )
    assert decision.restore_allowed is False
    assert decision.require_pre_restore_backup is True


def test_non_overwrite_restore_can_proceed_after_integrity_verification():
    decision = PerformanceRecoveryPolicy.recovery_decision(
        snapshot_exists=True,
        snapshot_verified=True,
        pre_restore_backup_exists=False,
        overwrite=False,
    )
    assert decision.restore_allowed is True


def test_update_requires_verified_manifest_artifact_backup_and_idle_runtime():
    policy = PerformanceRecoveryPolicy()
    assert policy.update_readiness(
        manifest_verified=False,
        artifact_verified=True,
        rollback_backup_exists=True,
        active_jobs=0,
        active_missions=0,
    ).ready is False
    assert policy.update_readiness(
        manifest_verified=True,
        artifact_verified=True,
        rollback_backup_exists=True,
        active_jobs=1,
        active_missions=0,
    ).ready is False
    assert policy.update_readiness(
        manifest_verified=True,
        artifact_verified=True,
        rollback_backup_exists=True,
        active_jobs=0,
        active_missions=0,
    ).ready is True


@pytest.mark.parametrize(
    "snapshot",
    [ResourceSnapshot(-1, 0, 10), ResourceSnapshot(0, 101, 10), ResourceSnapshot(0, 0, 101)],
)
def test_resource_snapshot_validation(snapshot):
    with pytest.raises(ValueError):
        snapshot.validate()
