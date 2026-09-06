from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from app.long_horizon_mission_runtime_v10 import LongHorizonMissionError, LongHorizonMissionRuntime
from app.mission_resume_coordinator_v10 import MissionResumeCoordinator, MissionResumeError


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


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


__all__ = ["MissionControlAPI", "create_mission_control_router"]
