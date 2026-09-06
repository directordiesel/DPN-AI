from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import Database
from app.mission_control_api_v10 import MissionPauseSignal, install_cooperative_pause_boundary
from app.mission_resume_coordinator_v10 import MissionResumeCoordinator


class _PassingCognitive:
    def derive_contract(self, objective: str):
        return SimpleNamespace(objective=objective)

    def verify_evidence(self, evidence, contract):
        return {
            "verdict": "pass",
            "confidence": 1.0,
            "verified": ["persisted restart evidence"],
            "issues": [],
        }


class _RestartableAgent:
    def effective_settings(self):
        return {
            "worker_model": "worker-test",
            "model": "worker-test",
            "think_level": "medium",
            "model_routes": {},
        }


class _RestartableOrchestrator:
    def __init__(self, db: Database):
        self.db = db
        self.agent = _RestartableAgent()
        self.cognitive = _PassingCognitive()
        self.executed: list[str] = []

    async def _execute_step(
        self,
        mission_id,
        objective,
        contract,
        step,
        conversation_id,
        project_id,
        attachments,
        selected_think,
        worker_model,
        effective,
    ):
        self.executed.append(str(step["id"]))
        return {
            "message": f"completed {step['id']}",
            "run_id": f"run-{step['id']}",
            "profile": step.get("role", "software"),
            "generated_files": [f"generated/{step['id']}.txt"],
            "tool_count": 2,
            "evidence_required": step.get("evidence_required", []),
        }, 2

    async def review(self, contract, evidence, model, think, perspective):
        return {
            "verdict": "pass",
            "confidence": 1.0,
            "summary": "restart evidence verified",
            "verified": ["unfinished step executed once"],
            "missing": [],
            "contradictions": [],
            "recommended_next_actions": [],
            "evaluator": perspective,
        }


def _create_persisted_mission(db: Database) -> tuple[str, str, str]:
    conversation_id = db.ensure_conversation(None, "restart acceptance")
    mission = db.create_mission(
        "Resume after restart without replaying completed work",
        conversation_id,
        None,
        "mission",
        {"planner": "planner-test", "worker": "worker-test", "reviewer": "reviewer-test"},
        {"max_seconds": 3600, "max_tool_calls": 100},
    )
    first = db.add_mission_step(mission["id"], 0, "software", "Completed before pause", "already completed", [])
    second = db.add_mission_step(mission["id"], 1, "software", "Resume after restart", "execute after restart", [first["id"]])
    db.update_mission_step(
        first["id"],
        "completed",
        {
            "message": "done before restart",
            "run_id": "run-before-restart",
            "generated_files": ["generated/before.txt"],
            "tool_count": 4,
            "evidence_required": ["before evidence"],
            "max_attempts": 2,
            "rollback": "none",
        },
    )
    db.update_mission_step(
        second["id"],
        "pending",
        {"evidence_required": ["after evidence"], "max_attempts": 2, "rollback": "restore snapshot"},
    )
    db.update_mission(mission["id"], "paused")
    return mission["id"], first["id"], second["id"]


def test_pause_restart_resume_completes_without_replaying_finished_step(tmp_path: Path):
    database_path = tmp_path / "restart.sqlite3"
    first_process_db = Database(database_path)
    mission_id, completed_step_id, pending_step_id = _create_persisted_mission(first_process_db)

    first_process = _RestartableOrchestrator(first_process_db)
    install_cooperative_pause_boundary(first_process)

    pending = first_process_db.get_mission_step(pending_step_id)
    with pytest.raises(MissionPauseSignal):
        asyncio.run(
            first_process._execute_step(
                mission_id,
                "Resume after restart without replaying completed work",
                SimpleNamespace(),
                pending,
                first_process_db.get_mission(mission_id)["conversation_id"],
                None,
                [],
                "medium",
                "worker-test",
                {},
            )
        )

    assert first_process.executed == []
    checkpoints_before_restart = first_process_db.list_checkpoints(mission_id)
    assert checkpoints_before_restart
    assert checkpoints_before_restart[0]["label"] == "v10-long-horizon-state"

    # Simulate process restart by constructing a fresh Database and orchestrator
    # against the same on-disk SQLite state. No Python execution state is reused.
    restarted_db = Database(database_path)
    restarted = _RestartableOrchestrator(restarted_db)
    result = asyncio.run(MissionResumeCoordinator(restarted).resume(mission_id))

    assert result.status == "completed"
    assert result.executed_step_ids == (pending_step_id,)
    assert completed_step_id in result.skipped_completed_step_ids
    assert restarted.executed == [pending_step_id]
    assert restarted_db.get_mission_step(completed_step_id)["attempts"] == 0
    assert restarted_db.get_mission_step(pending_step_id)["status"] == "completed"
    assert restarted_db.get_mission(mission_id)["status"] == "completed"

    checkpoints_after_restart = restarted_db.list_checkpoints(mission_id)
    assert any(item["label"] == "v10-long-horizon-state" for item in checkpoints_after_restart)
    latest_v10 = next(item for item in checkpoints_after_restart if item["label"] == "v10-long-horizon-state")
    assert latest_v10["state"]["lifecycle"] == "completed"
    assert latest_v10["state"]["cursor"]["next_step_id"] == ""
    assert latest_v10["state"]["budget"]["tool_calls_used"] >= 6
