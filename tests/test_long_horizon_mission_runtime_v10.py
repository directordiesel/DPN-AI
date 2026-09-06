from __future__ import annotations

import copy

import pytest

from app.long_horizon_mission_runtime_v10 import (
    LongHorizonCheckpointCodec,
    LongHorizonMissionError,
    LongHorizonMissionRuntime,
    MissionBudgetSnapshot,
    MissionCheckpointState,
    MissionCursor,
    MissionLifecycle,
    ResumeDisposition,
)


class FakeStore:
    def __init__(self):
        self.missions = {"m1": {"id": "m1", "status": "running"}}
        self.steps = {
            "m1": [
                {"id": "s1", "status": "completed"},
                {"id": "s2", "status": "pending"},
                {"id": "s3", "status": "pending"},
            ]
        }
        self.checkpoints = {"m1": []}

    def get_mission(self, mission_id):
        return copy.deepcopy(self.missions.get(mission_id))

    def list_mission_steps(self, mission_id):
        return copy.deepcopy(self.steps.get(mission_id, []))

    def add_checkpoint(self, mission_id, label, state, step_id=None):
        item = {
            "id": f"cp-{len(self.checkpoints.setdefault(mission_id, [])) + 1}",
            "mission_id": mission_id,
            "label": label,
            "state": copy.deepcopy(state),
            "step_id": step_id,
        }
        self.checkpoints[mission_id].insert(0, item)
        return copy.deepcopy(item)

    def list_checkpoints(self, mission_id, limit=100):
        return copy.deepcopy(self.checkpoints.get(mission_id, [])[:limit])


def state(
    lifecycle=MissionLifecycle.RUNNING,
    next_step="s2",
    failed=(),
    approvals=(),
    elapsed=10,
    tool_calls=3,
):
    return MissionCheckpointState(
        schema_version=1,
        lifecycle=lifecycle,
        cursor=MissionCursor(
            mission_id="m1",
            next_step_id=next_step,
            completed_step_ids=("s1",),
            failed_step_ids=tuple(failed),
            attempt=1,
        ),
        budget=MissionBudgetSnapshot(
            elapsed_seconds=elapsed,
            tool_calls_used=tool_calls,
            max_seconds=3600,
            max_tool_calls=100,
        ),
        evidence_ids=("e1",),
        artifact_refs=("generated/report.txt",),
        pending_approval_ids=tuple(approvals),
        reason="periodic checkpoint",
        revision=2,
    )


def test_checkpoint_round_trip_and_integrity():
    encoded = LongHorizonCheckpointCodec.encode(state())
    decoded = LongHorizonCheckpointCodec.decode(encoded)
    assert decoded.cursor.next_step_id == "s2"
    assert decoded.digest() == encoded["integrity_sha256"]


def test_checkpoint_tampering_fails_closed():
    encoded = LongHorizonCheckpointCodec.encode(state())
    encoded["cursor"]["next_step_id"] = "s3"
    with pytest.raises(LongHorizonMissionError, match="integrity verification failed"):
        LongHorizonCheckpointCodec.decode(encoded)


def test_runtime_persists_and_resumes_latest_verified_checkpoint():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    saved = runtime.checkpoint(state(), step_id="s1")
    decision = runtime.recovery_decision("m1")
    assert saved["label"] == runtime.LABEL
    assert decision.disposition == ResumeDisposition.RESUME
    assert decision.next_step_id == "s2"
    assert decision.checkpoint_id == saved["id"]


def test_runtime_skips_corrupt_newer_checkpoint_and_uses_older_verified_state():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    good = runtime.checkpoint(state(), step_id="s1")
    corrupt = LongHorizonCheckpointCodec.encode(state(next_step="s3"))
    corrupt["budget"]["tool_calls_used"] = 999
    store.add_checkpoint("m1", runtime.LABEL, corrupt, step_id="s1")
    decision = runtime.recovery_decision("m1")
    assert decision.disposition == ResumeDisposition.RESUME
    assert decision.checkpoint_id == good["id"]
    assert decision.next_step_id == "s2"


def test_unknown_step_reference_is_rejected():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    with pytest.raises(LongHorizonMissionError, match="unknown mission step"):
        runtime.checkpoint(state(next_step="not-a-step"))


def test_pending_approval_blocks_side_effect_replay():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    runtime.checkpoint(state(approvals=("approval-1",)))
    decision = runtime.recovery_decision("m1")
    assert decision.disposition == ResumeDisposition.STOP
    assert decision.pending_approval_ids == ("approval-1",)
    assert "cannot replay side effects" in decision.reason


def test_failed_step_routes_to_repair():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    runtime.checkpoint(state(lifecycle=MissionLifecycle.RECOVERING, failed=("s2",), next_step="s2"))
    decision = runtime.recovery_decision("m1")
    assert decision.disposition == ResumeDisposition.REPAIR
    assert decision.next_step_id == "s2"


def test_budget_exhaustion_stops_resume():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    exhausted = MissionCheckpointState(
        schema_version=1,
        lifecycle=MissionLifecycle.PAUSED,
        cursor=MissionCursor("m1", next_step_id="s2", completed_step_ids=("s1",)),
        budget=MissionBudgetSnapshot(3600, 5, 3600, 100),
    )
    runtime.checkpoint(exhausted)
    decision = runtime.recovery_decision("m1")
    assert decision.disposition == ResumeDisposition.STOP
    assert "budget" in decision.reason


def test_terminal_mission_never_resumes():
    store = FakeStore()
    store.missions["m1"]["status"] = "completed"
    runtime = LongHorizonMissionRuntime(store)
    decision = runtime.recovery_decision("m1")
    assert decision.disposition == ResumeDisposition.STOP
    assert "terminal" in decision.reason


def test_missing_verified_checkpoint_requires_replan():
    store = FakeStore()
    runtime = LongHorizonMissionRuntime(store)
    decision = runtime.recovery_decision("m1")
    assert decision.disposition == ResumeDisposition.REPLAN
