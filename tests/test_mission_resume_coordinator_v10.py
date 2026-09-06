from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import Database
from app.long_horizon_mission_runtime_v10 import (
    LongHorizonMissionRuntime,
    MissionBudgetSnapshot,
    MissionCheckpointState,
    MissionCursor,
    MissionLifecycle,
)
from app.mission_resume_coordinator_v10 import MissionResumeCoordinator, MissionResumeError


class FakeCognitive:
    def derive_contract(self, objective: str):
        return SimpleNamespace(objective=objective)

    def verify_evidence(self, evidence, contract):
        return {
            "verdict": "pass",
            "confidence": 1.0,
            "verified": [item.get("step") for item in evidence],
            "issues": [],
        }


class FakeAgent:
    def effective_settings(self):
        return {
            "worker_model": "worker-model",
            "model": "worker-model",
            "think_level": "medium",
            "model_routes": {},
        }


class FakeOrchestrator:
    def __init__(self, db: Database):
        self.db = db
        self.agent = FakeAgent()
        self.cognitive = FakeCognitive()
        self.executed = []

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
        self.executed.append(step["id"])
        return {
            "message": f"completed {step['title']}",
            "run_id": f"run-{step['id']}",
            "profile": step["role"],
            "generated_files": [f"generated/{step['ordinal']}.txt"],
            "tool_count": 2,
            "evidence_required": step.get("evidence_required", []),
        }, 2

    async def review(self, contract, evidence, model, think, perspective):
        return {
            "verdict": "pass",
            "confidence": 1.0,
            "summary": "resume evidence passed",
            "verified": [item.get("step") for item in evidence],
            "missing": [],
            "contradictions": [],
            "recommended_next_actions": [],
            "evaluator": perspective,
        }


def build_resumable_mission(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    conversation_id = db.ensure_conversation(None, "Resume test")
    mission = db.create_mission(
        "Finish the persisted work",
        conversation_id,
        None,
        "mission",
        {"planner": "planner-model", "worker": "worker-model", "reviewer": "reviewer-model"},
        {"max_seconds": 600, "max_tool_calls": 50},
    )
    first = db.add_mission_step(mission["id"], 0, "software", "First", "first", [])
    second = db.add_mission_step(mission["id"], 1, "software", "Second", "second", [first["id"]])
    db.update_mission_step(first["id"], "completed", {
        "message": "already done",
        "run_id": "run-first",
        "generated_files": ["generated/first.txt"],
        "tool_count": 3,
    })
    db.update_mission_step(second["id"], "pending", {
        "evidence_required": ["result"],
        "max_attempts": 2,
        "rollback": "restore",
        "phase": "planned",
    })
    db.update_mission(mission["id"], "paused")
    runtime = LongHorizonMissionRuntime(db)
    runtime.checkpoint(MissionCheckpointState(
        schema_version=1,
        lifecycle=MissionLifecycle.PAUSED,
        cursor=MissionCursor(
            mission_id=mission["id"],
            next_step_id=second["id"],
            completed_step_ids=(first["id"],),
        ),
        budget=MissionBudgetSnapshot(
            elapsed_seconds=20,
            tool_calls_used=3,
            max_seconds=600,
            max_tool_calls=50,
        ),
        evidence_ids=("run-first",),
        artifact_refs=("generated/first.txt",),
        reason="process stopped after first step",
        revision=1,
    ), step_id=first["id"])
    return db, mission, first, second


def test_resume_skips_completed_step_and_executes_only_cursor_step(tmp_path: Path):
    db, mission, first, second = build_resumable_mission(tmp_path)
    orchestrator = FakeOrchestrator(db)
    coordinator = MissionResumeCoordinator(orchestrator)

    result = asyncio.run(coordinator.resume(mission["id"]))

    assert result.status == "completed"
    assert result.executed_step_ids == (second["id"],)
    assert result.skipped_completed_step_ids == (first["id"],)
    assert orchestrator.executed == [second["id"]]
    assert db.get_mission_step(first["id"])["attempts"] == 0
    assert db.get_mission_step(second["id"])["status"] == "completed"
    assert db.get_mission(mission["id"])["status"] == "completed"
    latest = coordinator.runtime.latest_verified(mission["id"])
    assert latest is not None
    assert latest[1].lifecycle == MissionLifecycle.COMPLETED
    assert latest[1].budget.tool_calls_used == 5


def test_resume_refuses_checkpoint_database_completion_disagreement(tmp_path: Path):
    db, mission, first, _second = build_resumable_mission(tmp_path)
    db.update_mission_step(first["id"], "pending", {"phase": "unexpected-reset"})
    coordinator = MissionResumeCoordinator(FakeOrchestrator(db))

    with pytest.raises(MissionResumeError, match="disagrees"):
        asyncio.run(coordinator.resume(mission["id"]))


def test_resume_refuses_terminal_mission(tmp_path: Path):
    db, mission, _first, _second = build_resumable_mission(tmp_path)
    db.update_mission(mission["id"], "cancelled")
    coordinator = MissionResumeCoordinator(FakeOrchestrator(db))

    with pytest.raises(MissionResumeError, match="terminal"):
        asyncio.run(coordinator.resume(mission["id"]))


def test_resume_preserves_cumulative_budget(tmp_path: Path):
    db, mission, first, second = build_resumable_mission(tmp_path)
    runtime = LongHorizonMissionRuntime(db)
    runtime.checkpoint(MissionCheckpointState(
        schema_version=1,
        lifecycle=MissionLifecycle.PAUSED,
        cursor=MissionCursor(
            mission_id=mission["id"],
            next_step_id=second["id"],
            completed_step_ids=(first["id"],),
        ),
        budget=MissionBudgetSnapshot(
            elapsed_seconds=20,
            tool_calls_used=50,
            max_seconds=600,
            max_tool_calls=50,
        ),
        revision=2,
    ), step_id=first["id"])
    coordinator = MissionResumeCoordinator(FakeOrchestrator(db))

    with pytest.raises(MissionResumeError, match="budget"):
        asyncio.run(coordinator.resume(mission["id"]))
