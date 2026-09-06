from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from app.long_horizon_mission_runtime_v10 import (
    LongHorizonMissionError,
    LongHorizonMissionRuntime,
    MissionBudgetSnapshot,
    MissionCheckpointState,
    MissionCursor,
    MissionLifecycle,
)
from app.mission_resume_coordinator_v10 import MissionResumeCoordinator, MissionResumeError


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
MOUNT_STATE_KEY = "dpn_v10_mission_control_mounted"
PAUSE_BOUNDARY_KEY = "_dpn_v10_pause_boundary_installed"


class MissionPauseSignal(asyncio.CancelledError):
    """Cooperative stop raised only at a verified boundary before step side effects."""


def _mission_elapsed_seconds(mission: dict[str, Any]) -> int:
    raw = str(mission.get("created_at") or "").strip()
    if not raw:
        return 0
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        return 0


def _persist_pause_boundary(db: Any, mission_id: str, next_step_id: str) -> dict[str, Any]:
    mission = db.get_mission(mission_id)
    if not mission:
        raise MissionPauseSignal("mission disappeared before cooperative pause boundary")
    steps = db.list_mission_steps(mission_id)
    completed = tuple(str(step["id"]) for step in steps if step.get("status") == "completed")
    failed = tuple(str(step["id"]) for step in steps if step.get("status") == "failed")
    tool_calls = sum(
        max(0, int((step.get("result") or {}).get("tool_count") or 0))
        for step in steps
        if step.get("status") == "completed"
    )
    budget = mission.get("budget") or {}
    max_seconds = max(1, int(budget.get("max_seconds") or 86400))
    max_tool_calls = max(1, int(budget.get("max_tool_calls") or 10000))
    previous = LongHorizonMissionRuntime(db).latest_verified(mission_id)
    revision = int(previous[1].revision) + 1 if previous else 1
    state = MissionCheckpointState(
        schema_version=1,
        lifecycle=MissionLifecycle.PAUSED,
        cursor=MissionCursor(
            mission_id=mission_id,
            next_step_id=next_step_id,
            completed_step_ids=completed,
            failed_step_ids=failed,
            attempt=sum(max(0, int(step.get("attempts") or 0)) for step in steps),
        ),
        budget=MissionBudgetSnapshot(
            elapsed_seconds=_mission_elapsed_seconds(mission),
            tool_calls_used=tool_calls,
            max_seconds=max_seconds,
            max_tool_calls=max_tool_calls,
        ),
        evidence_ids=tuple(
            str((step.get("result") or {}).get("run_id"))
            for step in steps
            if step.get("status") == "completed" and str((step.get("result") or {}).get("run_id") or "").strip()
        ),
        artifact_refs=tuple(
            dict.fromkeys(
                str(path)
                for step in steps
                if step.get("status") == "completed"
                for path in ((step.get("result") or {}).get("generated_files") or [])
                if str(path).strip()
            )
        ),
        reason="operator pause honored at safe pre-step execution boundary",
        revision=revision,
    )
    return LongHorizonMissionRuntime(db).checkpoint(state, step_id=next_step_id)


def install_cooperative_pause_boundary(orchestrator: Any) -> bool:
    """Wrap the existing step executor so persisted pause state is honored safely.

    The guard runs after the orchestrator marks the step active but before its agent/tool
    execution begins. MissionPauseSignal inherits from asyncio.CancelledError rather than
    Exception, so the mature retry/failure loop does not misclassify an operator pause as
    a failed step. A verified v10 checkpoint is persisted first for restart recovery.
    """
    if bool(getattr(orchestrator, PAUSE_BOUNDARY_KEY, False)):
        return False
    original = getattr(orchestrator, "_execute_step", None)
    db = getattr(orchestrator, "db", None)
    if not callable(original) or db is None:
        raise RuntimeError("orchestrator does not expose the required cooperative pause contract")

    async def guarded_execute_step(mission_id: str, *args: Any, **kwargs: Any):
        mission = db.get_mission(mission_id)
        if mission and str(mission.get("status") or "") == "paused":
            step = args[2] if len(args) >= 3 else kwargs.get("step")
            step_id = str((step or {}).get("id") or "").strip()
            if not step_id:
                raise MissionPauseSignal("pause boundary could not identify the next mission step")
            _persist_pause_boundary(db, mission_id, step_id)
            db.audit(
                "mission.pause_boundary",
                f"Mission {mission_id} stopped at a safe execution boundary",
                {"mission_id": mission_id, "next_step_id": step_id},
            )
            raise MissionPauseSignal(f"mission paused before step {step_id}")
        return await original(mission_id, *args, **kwargs)

    setattr(orchestrator, "_execute_step", guarded_execute_step)
    setattr(orchestrator, PAUSE_BOUNDARY_KEY, True)
    return True


class MissionControlAPI:
    """HTTP-facing control plane for v10 long-horizon missions.

    Pause is cooperative: it records persisted intent and never interrupts a tool call
    in the middle of a possible side effect. The live orchestrator/resume runtime can
    honor that state at the next safe step boundary.
    """

    def __init__(self, db: Any, orchestrator: Any) -> None:
        self.db = db
        self.runtime = LongHorizonMissionRuntime(db)
        self.resume_coordinator = MissionResumeCoordinator(orchestrator)

    def recovery_status(self, mission_id: str) -> dict[str, Any]:
        mission = self.db.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")
        try:
            decision = self.runtime.recovery_decision(mission_id)
            latest = self.runtime.latest_verified(mission_id)
        except LongHorizonMissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        checkpoint = None
        state = None
        if latest:
            checkpoint, decoded = latest
            state = decoded.canonical_payload()
        return {
            "mission_id": mission_id,
            "mission_status": mission.get("status"),
            "recovery": {
                "disposition": decision.disposition.value,
                "reason": decision.reason,
                "checkpoint_id": decision.checkpoint_id,
                "next_step_id": decision.next_step_id,
                "pending_approval_ids": list(decision.pending_approval_ids),
            },
            "latest_verified_checkpoint": checkpoint,
            "verified_state": state,
        }

    def pause(self, mission_id: str) -> dict[str, Any]:
        mission = self.db.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")
        status = str(mission.get("status") or "")
        if status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail=f"Terminal mission cannot be paused: {status}")
        if status == "paused":
            return {"ok": True, "mission_id": mission_id, "status": "paused", "already_paused": True}
        self.db.update_mission(mission_id, "paused")
        self.db.audit(
            "mission.pause_requested",
            f"Pause requested for mission {mission_id}",
            {"mission_id": mission_id, "previous_status": status},
        )
        return {
            "ok": True,
            "mission_id": mission_id,
            "status": "paused",
            "cooperative": True,
            "message": "Pause persisted; in-flight work is not interrupted and execution stops at the next safe boundary.",
        }

    async def resume(self, mission_id: str, *, attachments: list[str] | None = None, think: bool | str | None = None) -> dict[str, Any]:
        mission = self.db.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")
        if str(mission.get("status") or "") in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="Terminal mission cannot be resumed")
        try:
            result = await self.resume_coordinator.resume(mission_id, attachments=attachments or [], think=think)
        except MissionResumeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self.db.audit(
            "mission.resumed",
            f"Resumed mission {mission_id}",
            {"mission_id": mission_id, "checkpoint_id": result.resumed_from_checkpoint_id},
        )
        return {"ok": result.status == "completed", **asdict(result)}


def create_mission_control_router(db: Any, orchestrator: Any) -> APIRouter:
    control = MissionControlAPI(db, orchestrator)
    router = APIRouter(prefix="/api/missions", tags=["missions-v10"])

    @router.get("/{mission_id}/recovery")
    def recovery_status(mission_id: str) -> dict[str, Any]:
        return control.recovery_status(mission_id)

    @router.get("/{mission_id}/checkpoint")
    def latest_checkpoint(mission_id: str) -> dict[str, Any]:
        status = control.recovery_status(mission_id)
        if not status["latest_verified_checkpoint"]:
            raise HTTPException(status_code=404, detail="No verified v10 checkpoint found")
        return {
            "mission_id": mission_id,
            "checkpoint": status["latest_verified_checkpoint"],
            "state": status["verified_state"],
        }

    @router.post("/{mission_id}/pause")
    def pause_mission(mission_id: str) -> dict[str, Any]:
        return control.pause(mission_id)

    @router.post("/{mission_id}/resume")
    async def resume_mission(mission_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        attachments = body.get("attachments") or []
        if not isinstance(attachments, list) or any(not isinstance(item, str) for item in attachments):
            raise HTTPException(status_code=422, detail="attachments must be a list of strings")
        think = body.get("think")
        if not (think is None or isinstance(think, (bool, str))):
            raise HTTPException(status_code=422, detail="think must be boolean, string, or null")
        return await control.resume(mission_id, attachments=attachments, think=think)

    return router


def mount_mission_control_router(app: FastAPI, db: Any, orchestrator: Any) -> bool:
    """Mount v10 mission controls exactly once on the live FastAPI application."""
    install_cooperative_pause_boundary(orchestrator)
    if bool(getattr(app.state, MOUNT_STATE_KEY, False)):
        return False
    app.include_router(create_mission_control_router(db, orchestrator))
    setattr(app.state, MOUNT_STATE_KEY, True)
    return True


__all__ = [
    "MissionControlAPI",
    "MissionPauseSignal",
    "create_mission_control_router",
    "install_cooperative_pause_boundary",
    "mount_mission_control_router",
]
