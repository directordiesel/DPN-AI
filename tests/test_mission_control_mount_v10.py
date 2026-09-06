from __future__ import annotations

import sys
from types import SimpleNamespace

from fastapi import FastAPI

from app.job_supervisor import JobSupervisor
from app.mission_control_api_v10 import mount_mission_control_router


class _FakeOrchestrator:
    def __init__(self, db):
        self.db = db
        self.agent = SimpleNamespace()
        self.cognitive = SimpleNamespace()

    async def _execute_step(self, *args, **kwargs):
        raise AssertionError("execution should not run while mounting routes")

    async def review(self, *args, **kwargs):
        raise AssertionError("review should not run while mounting routes")


class _FakeDB:
    def requeue_interrupted_jobs(self):
        return 0

    def list_background_jobs(self, *args, **kwargs):
        return []


def _paths(app: FastAPI) -> list[str]:
    return [route.path for route in app.routes]


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
    # must never duplicate on repeated startup.
    assert supervisor._mount_v10_mission_control() is False
