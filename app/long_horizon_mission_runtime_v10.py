from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Protocol


class LongHorizonMissionError(ValueError):
    """Raised when persisted long-horizon mission state cannot be trusted."""


class MissionLifecycle(str, Enum):
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResumeDisposition(str, Enum):
    RESUME = "resume"
    REPAIR = "repair"
    REPLAN = "replan"
    STOP = "stop"


@dataclass(frozen=True)
class MissionCursor:
    mission_id: str
    next_step_id: str = ""
    completed_step_ids: tuple[str, ...] = ()
    failed_step_ids: tuple[str, ...] = ()
    attempt: int = 0

    def validate(self) -> None:
        if not self.mission_id.strip():
            raise LongHorizonMissionError("mission id is required")
        if self.attempt < 0:
            raise LongHorizonMissionError("mission attempt must be non-negative")
        if len(set(self.completed_step_ids)) != len(self.completed_step_ids):
            raise LongHorizonMissionError("completed step ids must be unique")
        if len(set(self.failed_step_ids)) != len(self.failed_step_ids):
            raise LongHorizonMissionError("failed step ids must be unique")
        if set(self.completed_step_ids) & set(self.failed_step_ids):
            raise LongHorizonMissionError("a step cannot be both completed and failed")


@dataclass(frozen=True)
class MissionBudgetSnapshot:
    elapsed_seconds: int
    tool_calls_used: int
    max_seconds: int
    max_tool_calls: int

    def validate(self) -> None:
        for name, value in (
            ("elapsed_seconds", self.elapsed_seconds),
            ("tool_calls_used", self.tool_calls_used),
            ("max_seconds", self.max_seconds),
            ("max_tool_calls", self.max_tool_calls),
        ):
            if value < 0:
                raise LongHorizonMissionError(f"{name} must be non-negative")
        if self.max_seconds < 1 or self.max_tool_calls < 1:
            raise LongHorizonMissionError("mission limits must be positive")

    @property
    def exhausted(self) -> bool:
        return self.elapsed_seconds >= self.max_seconds or self.tool_calls_used >= self.max_tool_calls


@dataclass(frozen=True)
class MissionCheckpointState:
    schema_version: int
    lifecycle: MissionLifecycle
    cursor: MissionCursor
    budget: MissionBudgetSnapshot
    evidence_ids: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    pending_approval_ids: tuple[str, ...] = ()
    reason: str = ""
    revision: int = 1

    def validate(self) -> None:
        if self.schema_version != 1:
            raise LongHorizonMissionError("unsupported long-horizon checkpoint schema version")
        self.cursor.validate()
        self.budget.validate()
        if self.revision < 1:
            raise LongHorizonMissionError("checkpoint revision must be >= 1")
        for collection_name, values in (
            ("evidence ids", self.evidence_ids),
            ("artifact refs", self.artifact_refs),
            ("pending approval ids", self.pending_approval_ids),
        ):
            if len(set(values)) != len(values):
                raise LongHorizonMissionError(f"{collection_name} must be unique")
        if self.lifecycle in {MissionLifecycle.COMPLETED, MissionLifecycle.FAILED, MissionLifecycle.CANCELLED} and self.cursor.next_step_id:
            raise LongHorizonMissionError("terminal checkpoints cannot contain a next step")

    def canonical_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "lifecycle": self.lifecycle.value,
            "cursor": {
                "mission_id": self.cursor.mission_id,
                "next_step_id": self.cursor.next_step_id,
                "completed_step_ids": list(self.cursor.completed_step_ids),
                "failed_step_ids": list(self.cursor.failed_step_ids),
                "attempt": self.cursor.attempt,
            },
            "budget": {
                "elapsed_seconds": self.budget.elapsed_seconds,
                "tool_calls_used": self.budget.tool_calls_used,
                "max_seconds": self.budget.max_seconds,
                "max_tool_calls": self.budget.max_tool_calls,
            },
            "evidence_ids": list(self.evidence_ids),
            "artifact_refs": list(self.artifact_refs),
            "pending_approval_ids": list(self.pending_approval_ids),
            "reason": self.reason,
            "revision": self.revision,
        }

    def digest(self) -> str:
        encoded = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RecoveryDecision:
    disposition: ResumeDisposition
    reason: str
    checkpoint_id: str = ""
    next_step_id: str = ""
    pending_approval_ids: tuple[str, ...] = ()


class MissionCheckpointStore(Protocol):
    def add_checkpoint(self, mission_id: str, label: str, state: dict[str, Any], step_id: str | None = None) -> dict[str, Any]: ...
    def list_checkpoints(self, mission_id: str, limit: int = 100) -> list[dict[str, Any]]: ...
    def get_mission(self, mission_id: str) -> dict[str, Any] | None: ...
    def list_mission_steps(self, mission_id: str) -> list[dict[str, Any]]: ...


class LongHorizonCheckpointCodec:
    @staticmethod
    def encode(state: MissionCheckpointState) -> dict[str, Any]:
        payload = state.canonical_payload()
        payload["integrity_sha256"] = state.digest()
        return payload

    @staticmethod
    def decode(payload: dict[str, Any]) -> MissionCheckpointState:
        if not isinstance(payload, dict):
            raise LongHorizonMissionError("checkpoint payload must be an object")
        integrity = str(payload.get("integrity_sha256") or "").strip()
        if not integrity:
            raise LongHorizonMissionError("checkpoint integrity digest is required")
        cursor_data = payload.get("cursor") or {}
        budget_data = payload.get("budget") or {}
        try:
            state = MissionCheckpointState(
                schema_version=int(payload.get("schema_version")),
                lifecycle=MissionLifecycle(str(payload.get("lifecycle"))),
                cursor=MissionCursor(
                    mission_id=str(cursor_data.get("mission_id") or ""),
                    next_step_id=str(cursor_data.get("next_step_id") or ""),
                    completed_step_ids=tuple(str(x) for x in cursor_data.get("completed_step_ids", [])),
                    failed_step_ids=tuple(str(x) for x in cursor_data.get("failed_step_ids", [])),
                    attempt=int(cursor_data.get("attempt", 0)),
                ),
                budget=MissionBudgetSnapshot(
                    elapsed_seconds=int(budget_data.get("elapsed_seconds", 0)),
                    tool_calls_used=int(budget_data.get("tool_calls_used", 0)),
                    max_seconds=int(budget_data.get("max_seconds", 0)),
                    max_tool_calls=int(budget_data.get("max_tool_calls", 0)),
                ),
                evidence_ids=tuple(str(x) for x in payload.get("evidence_ids", [])),
                artifact_refs=tuple(str(x) for x in payload.get("artifact_refs", [])),
                pending_approval_ids=tuple(str(x) for x in payload.get("pending_approval_ids", [])),
                reason=str(payload.get("reason") or ""),
                revision=int(payload.get("revision", 1)),
            )
        except (TypeError, ValueError) as exc:
            raise LongHorizonMissionError(f"invalid checkpoint payload: {exc}") from exc
        state.validate()
        if not _constant_time_text_equal(state.digest(), integrity):
            raise LongHorizonMissionError("checkpoint integrity verification failed")
        return state


def _constant_time_text_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for a, b in zip(left.encode("utf-8"), right.encode("utf-8")):
        result |= a ^ b
    return result == 0


class LongHorizonMissionRuntime:
    """Durable checkpoint/recovery layer for v10 long-running missions.

    The runtime does not replay side effects. It reconstructs a safe resume point from
    persisted mission/step/checkpoint evidence and requires any approval-waiting work
    to remain blocked until the original approval is resolved.
    """

    LABEL = "v10-long-horizon-state"

    def __init__(self, store: MissionCheckpointStore) -> None:
        self.store = store

    def checkpoint(self, state: MissionCheckpointState, *, step_id: str | None = None) -> dict[str, Any]:
        state.validate()
        mission = self.store.get_mission(state.cursor.mission_id)
        if mission is None:
            raise LongHorizonMissionError("cannot checkpoint unknown mission")
        known_steps = {str(item.get("id")) for item in self.store.list_mission_steps(state.cursor.mission_id)}
        referenced = set(state.cursor.completed_step_ids) | set(state.cursor.failed_step_ids)
        if state.cursor.next_step_id:
            referenced.add(state.cursor.next_step_id)
        if not referenced.issubset(known_steps):
            raise LongHorizonMissionError("checkpoint references an unknown mission step")
        if step_id is not None and step_id not in known_steps:
            raise LongHorizonMissionError("checkpoint step id is not part of the mission")
        return self.store.add_checkpoint(
            state.cursor.mission_id,
            self.LABEL,
            LongHorizonCheckpointCodec.encode(state),
            step_id=step_id,
        )

    def latest_verified(self, mission_id: str) -> tuple[dict[str, Any], MissionCheckpointState] | None:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise LongHorizonMissionError("unknown mission")
        for checkpoint in self.store.list_checkpoints(mission_id, limit=100):
            if str(checkpoint.get("label") or "") != self.LABEL:
                continue
            raw_state = checkpoint.get("state")
            if raw_state is None:
                raw_state = checkpoint.get("state_json")
                if isinstance(raw_state, str):
                    try:
                        raw_state = json.loads(raw_state)
                    except json.JSONDecodeError:
                        continue
            try:
                decoded = LongHorizonCheckpointCodec.decode(raw_state)
            except LongHorizonMissionError:
                continue
            if decoded.cursor.mission_id != mission_id:
                continue
            return checkpoint, decoded
        return None

    def recovery_decision(self, mission_id: str) -> RecoveryDecision:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise LongHorizonMissionError("unknown mission")
        status = str(mission.get("status") or "")
        if status in {MissionLifecycle.COMPLETED.value, MissionLifecycle.FAILED.value, MissionLifecycle.CANCELLED.value}:
            return RecoveryDecision(ResumeDisposition.STOP, f"mission is already terminal: {status}")

        latest = self.latest_verified(mission_id)
        if latest is None:
            return RecoveryDecision(ResumeDisposition.REPLAN, "no verified v10 checkpoint exists")
        checkpoint, state = latest

        if state.budget.exhausted:
            return RecoveryDecision(
                ResumeDisposition.STOP,
                "mission budget was exhausted at the latest verified checkpoint",
                checkpoint_id=str(checkpoint.get("id") or ""),
            )
        if state.pending_approval_ids:
            return RecoveryDecision(
                ResumeDisposition.STOP,
                "mission is waiting on unresolved approval state and cannot replay side effects",
                checkpoint_id=str(checkpoint.get("id") or ""),
                pending_approval_ids=state.pending_approval_ids,
            )
        if state.lifecycle in {MissionLifecycle.BLOCKED, MissionLifecycle.RECOVERING} or state.cursor.failed_step_ids:
            return RecoveryDecision(
                ResumeDisposition.REPAIR,
                "resume through bounded repair from the latest verified checkpoint",
                checkpoint_id=str(checkpoint.get("id") or ""),
                next_step_id=state.cursor.next_step_id,
            )
        if state.lifecycle in {MissionLifecycle.RUNNING, MissionLifecycle.PAUSED, MissionLifecycle.PLANNING}:
            return RecoveryDecision(
                ResumeDisposition.RESUME,
                "resume from the latest verified checkpoint without replaying completed steps",
                checkpoint_id=str(checkpoint.get("id") or ""),
                next_step_id=state.cursor.next_step_id,
            )
        return RecoveryDecision(ResumeDisposition.REPLAN, "checkpoint state is not safely resumable")


__all__ = [
    "LongHorizonCheckpointCodec",
    "LongHorizonMissionError",
    "LongHorizonMissionRuntime",
    "MissionBudgetSnapshot",
    "MissionCheckpointState",
    "MissionCursor",
    "MissionLifecycle",
    "RecoveryDecision",
    "ResumeDisposition",
]
