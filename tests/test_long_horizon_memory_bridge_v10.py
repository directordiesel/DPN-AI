from __future__ import annotations

import pytest

from app.advanced_layered_memory_v10 import MemoryContext
from app.long_horizon_memory_bridge_v10 import LongHorizonMemoryBridge
from app.long_horizon_mission_runtime_v10 import (
    LongHorizonCheckpointCodec,
    MissionBudgetSnapshot,
    MissionCheckpointState,
    MissionCursor,
    MissionLifecycle,
)


class FakeStore:
    def __init__(self) -> None:
        self.mission = {
            "id": "m-1",
            "status": "completed",
            "objective": "Safely finish the long-running integration mission.",
            "project_id": "project-1",
            "conversation_id": "conversation-1",
            "result": {
                "deterministic_review": {"verdict": "pass", "confidence": 1.0},
                "security_review": {"verdict": "pass", "confidence": 0.95},
            },
        }
        self.steps = [
            {"id": "s-1", "title": "Inspect repository", "status": "completed", "result": {"run_id": "run-1"}},
            {"id": "s-2", "title": "Run verification", "status": "completed", "result": {"run_id": "run-2"}},
        ]
        state = MissionCheckpointState(
            schema_version=1,
            lifecycle=MissionLifecycle.COMPLETED,
            cursor=MissionCursor(
                mission_id="m-1",
                next_step_id="",
                completed_step_ids=("s-1", "s-2"),
                failed_step_ids=(),
                attempt=2,
            ),
            budget=MissionBudgetSnapshot(
                elapsed_seconds=90,
                tool_calls_used=4,
                max_seconds=600,
                max_tool_calls=40,
            ),
            evidence_ids=("run-1", "run-2"),
            artifact_refs=("report.json",),
            reason="mission completed verification",
            revision=5,
        )
        self.checkpoints = [
            {
                "id": "cp-5",
                "label": "v10-long-horizon-state",
                "state": LongHorizonCheckpointCodec.encode(state),
            }
        ]

    def get_mission(self, mission_id: str):
        return self.mission if mission_id == "m-1" else None

    def list_mission_steps(self, mission_id: str):
        return list(self.steps) if mission_id == "m-1" else []

    def list_checkpoints(self, mission_id: str, limit: int = 100):
        return list(self.checkpoints[:limit]) if mission_id == "m-1" else []


class FakeMemory:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests = []

    async def remember(self, request):
        self.requests.append(request)
        if self.fail:
            return {"ok": False, "stored": False, "error": "storage unavailable"}
        return {"ok": True, "stored": True, "memory_id": "mem-episode-1"}


@pytest.mark.asyncio
async def test_verified_completed_mission_promotes_to_episodic_memory():
    store = FakeStore()
    memory = FakeMemory()
    bridge = LongHorizonMemoryBridge(store, memory)

    result = await bridge.promote_completed_mission("m-1")

    assert result.stored is True
    assert result.episodic_memory_id == "mem-episode-1"
    assert result.completed_step_count == 2
    assert result.evidence_ids == ("run-1", "run-2")
    assert len(memory.requests) == 1
    request = memory.requests[0]
    assert request.layer.value == "episodic"
    assert request.knowledge_class.value == "episode"
    assert request.provenance.source_type == "long_horizon_mission"
    assert request.provenance.source_id == "cp-5"
    assert request.provenance.evidence_ids == ("run-1", "run-2")
    assert request.context.project_id == "project-1"
    assert request.context.conversation_id == "conversation-1"
    assert '"security_review"' not in request.content
    assert '"result"' not in request.content
    assert '"checkpoint_id":"cp-5"' in request.content


@pytest.mark.asyncio
async def test_noncompleted_mission_fails_before_memory_write():
    store = FakeStore()
    store.mission["status"] = "paused"
    memory = FakeMemory()

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission("m-1")

    assert result.stored is False
    assert "completed missions" in result.reason
    assert memory.requests == []


@pytest.mark.asyncio
async def test_integrity_tampered_checkpoint_fails_closed():
    store = FakeStore()
    store.checkpoints[0]["state"]["revision"] = 999
    memory = FakeMemory()

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission("m-1")

    assert result.stored is False
    assert "verified" in result.reason.lower()
    assert memory.requests == []


@pytest.mark.asyncio
async def test_checkpoint_and_persisted_step_state_must_match_exactly():
    store = FakeStore()
    store.steps[1]["status"] = "blocked"
    memory = FakeMemory()

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission("m-1")

    assert result.stored is False
    assert "disagrees" in result.reason
    assert memory.requests == []


@pytest.mark.asyncio
async def test_failed_security_review_blocks_promotion():
    store = FakeStore()
    store.mission["result"]["security_review"]["verdict"] = "fail"
    memory = FakeMemory()

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission("m-1")

    assert result.stored is False
    assert "security verification" in result.reason
    assert memory.requests == []


@pytest.mark.asyncio
async def test_pending_approval_state_blocks_promotion():
    store = FakeStore()
    payload = store.checkpoints[0]["state"]
    state = MissionCheckpointState(
        schema_version=1,
        lifecycle=MissionLifecycle.COMPLETED,
        cursor=MissionCursor(
            mission_id="m-1",
            completed_step_ids=("s-1", "s-2"),
            attempt=2,
        ),
        budget=MissionBudgetSnapshot(90, 4, 600, 40),
        evidence_ids=("run-1", "run-2"),
        artifact_refs=("report.json",),
        pending_approval_ids=("approval-1",),
        reason="completed but pending approval should be impossible",
        revision=6,
    )
    store.checkpoints[0]["state"] = LongHorizonCheckpointCodec.encode(state)
    memory = FakeMemory()

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission("m-1")

    assert result.stored is False
    assert "unresolved execution state" in result.reason
    assert memory.requests == []


@pytest.mark.asyncio
async def test_sensitive_flag_is_forwarded_without_approval_boolean():
    store = FakeStore()
    memory = FakeMemory()

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission(
        "m-1",
        context=MemoryContext(project_id="project-override"),
        sensitive=True,
    )

    assert result.stored is True
    request = memory.requests[0]
    assert request.sensitive is True
    assert request.context.project_id == "project-override"
    assert not hasattr(request, "approval_granted")


@pytest.mark.asyncio
async def test_memory_storage_failure_is_reported_not_hidden():
    store = FakeStore()
    memory = FakeMemory(fail=True)

    result = await LongHorizonMemoryBridge(store, memory).promote_completed_mission("m-1")

    assert result.stored is False
    assert result.reason == "storage unavailable"
    assert len(memory.requests) == 1
