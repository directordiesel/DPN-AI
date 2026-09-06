from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.db import Database
from app.long_horizon_mission_runtime_v10 import (
    LongHorizonMissionRuntime,
    MissionBudgetSnapshot,
    MissionCheckpointState,
    MissionCursor,
    MissionLifecycle,
)
from app.mission_control_api_v10 import MissionControlAPI


class FakeCognitive:
    def derive_contract(self, objective):
        return SimpleNamespace(objective=objective)

    def verify_evidence(self, evidence, contract):
        return {"verdict": "pass", "confidence": 1.0, "issues": []}


class FakeAgent:
    def effective_settings(self):
        return {"model": "worker", "worker_model": "worker", "think_level": "medium"}


class FakeOrchestrator:
    def __init__(self, db):
        self.db = db
        self.agent = FakeAgent()
        self.cognitive = FakeCognitive()
        self.executed = []

    async def _execute_step(self, mission_id, objective, contract, step, conversation_id, project_id, attachments, think, worker_model, effective):
        self.executed.append(step["id"])
        return {"message": "done", "run_id": f"run-{step['id']}", "generated_files": [], "profile": step["role"]}, 1

    async def review(self, contract, evidence, model, think, perspective):
        return {"verdict": "pass", "confidence": 1.0, "summary": "ok", "verified": [], "missing": [], "contradictions": [], "recommended_next_actions": []}


def make_mission(tmp_path):
    db = Database(tmp_path / "data.sqlite3")
    conversation_id = db.ensure_conversation(None, "resume test")
    mission = db.create_mission(
        "Finish durable work",
        conversation_id,
        None,
        "mission",
        {"planner": "planner", "worker": "worker", "reviewer": "reviewer"},
        {"max_seconds": 600, "max_tool_calls": 20},
    )
    first = db.add_mission_step(mission["id"], 0, "software", "first", "first", [])
    second = db.add_mission_step(mission["id"], 1, "software", "second", "second", [first["id"]])
    db.update_mission_step(first["id"], "completed", {"run_id": "run-first", "generated_files": []})
    db.update_mission_step(second["id"], result={"max_attempts": 1, "evidence_required": [], "rollback": ""})
    db.update_mission(mission["id"], "paused")
    runtime = LongHorizonMissionRuntime(db)
    runtime.checkpoint(
        MissionCheckpointState(
            schema_version=1,
            lifecycle=MissionLifecycle.PAUSED,
            cursor=MissionCursor(mission["id"], second["id"], (first["id"],), (), 1),
            budget=MissionBudgetSnapshot(10, 2, 600, 20),
            evidence_ids=("run-first",),
            revision=1,
        ),
        step_id=second["id"],
    )
    return db, mission, first, second


def test_recovery_status_exposes_verified_checkpoint(tmp_path):
    db, mission, _first, second = make_mission(tmp_path)
    control = MissionControlAPI(db, FakeOrchestrator(db))
    result = control.recovery_status(mission["id"])
    assert result["mission_status"] == "paused"
    assert result["recovery"]["disposition"] == "resume"
    assert result["recovery"]["next_step_id"] == second["id"]
    assert result["verified_state"]["budget"]["tool_calls_used"] == 2


def test_pause_is_idempotent_and_terminal_safe(tmp_path):
    db, mission, _first, _second = make_mission(tmp_path)
    control = MissionControlAPI(db, FakeOrchestrator(db))
    result = control.pause(mission["id"])
    assert result["already_paused"] is True
    db.update_mission(mission["id"], "cancelled")
    with pytest.raises(HTTPException) as exc:
        control.pause(mission["id"])
    assert exc.value.status_code == 409


def test_resume_api_executes_only_unfinished_step(tmp_path):
    db, mission, first, second = make_mission(tmp_path)
    orchestrator = FakeOrchestrator(db)
    control = MissionControlAPI(db, orchestrator)
    result = asyncio.run(control.resume(mission["id"]))
    assert result["ok"] is True
    assert orchestrator.executed == [second["id"]]
    assert first["id"] in result["skipped_completed_step_ids"]
    assert second["id"] in result["executed_step_ids"]
    assert db.get_mission(mission["id"])["status"] == "completed"


def test_missing_mission_fails_cleanly(tmp_path):
    db = Database(tmp_path / "data.sqlite3")
    control = MissionControlAPI(db, FakeOrchestrator(db))
    with pytest.raises(HTTPException) as exc:
        control.recovery_status("missing")
    assert exc.value.status_code == 404
