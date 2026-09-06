from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.job_supervisor import JobSupervisor
from app.mission_control_api_v10 import (
    MissionPauseSignal,
    install_cooperative_pause_boundary,
    mount_mission_control_router,
)


class _FakeOrchestrator:
    def __init__(self, db):
        self.db = db
        self.agent = SimpleNamespace()
        self.cognitive = SimpleNamespace()
        self.execute_calls = 0

    async def _execute_step(self, *args, **kwargs):
        self.execute_calls += 1
        return {"ok": True}, 0

    async def review(self, *args, **kwargs):
        raise AssertionError("review should not run while mounting routes")


class _FakeDB:
    def __init__(self):
        self.mission = None
        self.steps = []
        self.checkpoints = []
        self.audits = []

    def requeue_interrupted_jobs(self):
        return 0

    def list_background_jobs(self, *args, **kwargs):
        return []

    def get_mission(self, mission_id):
        return self.mission if self.mission and self.mission.get("id") == mission_id else None

    def list_mission_steps(self, mission_id):
        return list(self.steps)

    def list_checkpoints(self, mission_id, limit=100):
        return list(reversed(self.checkpoints[-limit:]))

    def add_checkpoint(self, mission_id, label, state, step_id=None):
        item = {"id": f"cp-{len(self.checkpoints) + 1}", "mission_id": mission_id, "label": label, "state": state, "step_id": step_id}
        self.checkpoints.append(item)
        return item

    def audit(self, event, message, metadata=None):
        self.audits.append((event, message, metadata or {}))


def _paths(app: FastAPI) -> list[str]:
    # FastAPI 0.141+ may preserve included routers as nested route objects rather
    # than flattening every child onto app.routes. OpenAPI is the public routing
    # contract and accurately proves the mounted endpoints are reachable.
    app.openapi_schema = None
    return list((app.openapi().get("paths") or {}).keys())


def test_mount_mission_control_router_is_idempotent():
    app = FastAPI()
    db = _FakeDB()
    orchestrator = _FakeOrchestrator(db)

    assert mount_mission_control_router(app, db, orchestrator) is True
    first_paths = _paths(app)
    assert "/api/missions/{mission_id}/recovery" in first_paths
    assert "/api/missions/{mission_id}/checkpoint" in first_paths
    assert "/api/missions/{mission_id}/pause" in first_paths
    assert "/api/missions/{mission_id}/resume" in first_paths

    assert mount_mission_control_router(app, db, orchestrator) is False
    assert _paths(app) == first_paths


def test_job_supervisor_mounts_routes_into_loaded_main_app(monkeypatch):
    app = FastAPI()
    db = _FakeDB()
    orchestrator = _FakeOrchestrator(db)
    supervisor = JobSupervisor(db, SimpleNamespace(), orchestrator, SimpleNamespace(), max_concurrency=1)

    monkeypatch.setitem(sys.modules, "app.main", SimpleNamespace(app=app))
    assert supervisor._mount_v10_mission_control() is True
    assert "/api/missions/{mission_id}/resume" in _paths(app)

    # Lifespan start can be invoked more than once during tests/reload. Routes
    # and the pause boundary must never duplicate on repeated startup.
    assert supervisor._mount_v10_mission_control() is False


def test_pause_boundary_persists_verified_cursor_before_execution():
    db = _FakeDB()
    db.mission = {
        "id": "mission-1",
        "status": "paused",
        "created_at": "2026-09-06T03:00:00+00:00",
        "budget": {"max_seconds": 3600, "max_tool_calls": 100},
    }
    db.steps = [
        {
            "id": "step-1",
            "status": "completed",
            "attempts": 1,
            "result": {"run_id": "run-1", "tool_count": 3, "generated_files": ["a.txt"]},
        },
        {"id": "step-2", "status": "running", "attempts": 1, "result": {}},
    ]
    orchestrator = _FakeOrchestrator(db)
    assert install_cooperative_pause_boundary(orchestrator) is True

    with pytest.raises(MissionPauseSignal):
        asyncio.run(orchestrator._execute_step("mission-1", "objective", SimpleNamespace(), db.steps[1], "conversation", None, [], "medium", "model", {}))

    assert orchestrator.execute_calls == 0
    assert db.checkpoints
    state = db.checkpoints[-1]["state"]
    assert state["lifecycle"] == "paused"
    assert state["cursor"]["completed_step_ids"] == ["step-1"]
    assert state["cursor"]["next_step_id"] == "step-2"
    assert state["budget"]["tool_calls_used"] == 3
    assert state["integrity_sha256"]
    assert any(event == "mission.pause_boundary" for event, _message, _metadata in db.audits)


def test_pause_boundary_allows_execution_when_mission_is_running():
    db = _FakeDB()
    db.mission = {"id": "mission-1", "status": "running", "budget": {"max_seconds": 3600, "max_tool_calls": 100}}
    db.steps = [{"id": "step-1", "status": "running", "attempts": 1, "result": {}}]
    orchestrator = _FakeOrchestrator(db)
    install_cooperative_pause_boundary(orchestrator)

    result, tool_count = asyncio.run(orchestrator._execute_step("mission-1", "objective", SimpleNamespace(), db.steps[0], "conversation", None, [], "medium", "model", {}))
    assert result == {"ok": True}
    assert tool_count == 0
    assert orchestrator.execute_calls == 1
    assert not db.checkpoints
