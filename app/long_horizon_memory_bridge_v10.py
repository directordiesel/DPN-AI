from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    KnowledgeClass,
    MemoryContext,
    MemoryLayer,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.long_horizon_mission_runtime_v10 import (
    LongHorizonMissionError,
    LongHorizonMissionRuntime,
    MissionLifecycle,
)


class LongHorizonMemoryBridgeError(ValueError):
    """Raised when long-horizon mission state is not trustworthy enough for memory."""


@dataclass(frozen=True)
class MissionMemoryPromotionResult:
    mission_id: str
    stored: bool
    episodic_memory_id: str = ""
    completed_step_count: int = 0
    evidence_ids: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    reason: str = ""


class LongHorizonMemoryBridge:
    """Promote verified terminal mission evidence into episodic layered memory.

    This bridge deliberately does not promote mission prose into semantic facts. Batch 8
    semantic promotion remains reserved for evidence-backed fact workflows (for example,
    the Deep Research memory bridge) until controlled promotion/supersession is added.

    Trust requirements are rechecked from persistence immediately before memory writes:
    * the mission exists and is persisted as completed;
    * the latest integrity-verified v10 checkpoint is COMPLETED;
    * the checkpoint has no failed/next-step/pending-approval state;
    * every checkpoint-completed step exists and is still persisted as completed;
    * no extra persisted completed step is omitted from checkpoint completion evidence;
    * mission deterministic review passed and security review did not fail.

    Only bounded operational summaries, verified checkpoint evidence identifiers, and
    artifact references are persisted. Raw tool arguments, approval payloads, credentials,
    and arbitrary provider transcripts are never copied into the memory record.
    """

    MAX_OBJECTIVE_CHARS = 4_000
    MAX_STEP_TITLE_CHARS = 240
    MAX_STEPS = 256
    MAX_EVIDENCE_IDS = 128
    MAX_ARTIFACT_REFS = 128

    def __init__(self, store: Any, memory: AdvancedLayeredMemory) -> None:
        required = ("get_mission", "list_mission_steps", "list_checkpoints")
        if any(not hasattr(store, name) for name in required):
            raise LongHorizonMemoryBridgeError("mission store does not expose the required persistence contract")
        self.store = store
        self.memory = memory
        self.runtime = LongHorizonMissionRuntime(store)

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _bounded(cls, value: Any, limit: int) -> str:
        cleaned = cls._clean(value)
        return cleaned if len(cleaned) <= limit else cleaned[: max(0, limit - 1)] + "…"

    @staticmethod
    def _review_verdict(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        return str(value.get("verdict") or "").strip().lower()

    def _validate_terminal_mission(self, mission_id: str) -> tuple[dict[str, Any], Any, list[dict[str, Any]]]:
        mission_id = self._clean(mission_id)
        if not mission_id:
            raise LongHorizonMemoryBridgeError("mission id is required")
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise LongHorizonMemoryBridgeError("unknown mission")
        if self._clean(mission.get("status")).lower() != MissionLifecycle.COMPLETED.value:
            raise LongHorizonMemoryBridgeError("only persisted completed missions can be promoted")

        try:
            latest = self.runtime.latest_verified(mission_id)
        except LongHorizonMissionError as exc:
            raise LongHorizonMemoryBridgeError(str(exc)) from exc
        if latest is None:
            raise LongHorizonMemoryBridgeError("no integrity-verified long-horizon checkpoint is available")
        checkpoint, state = latest
        if state.lifecycle != MissionLifecycle.COMPLETED:
            raise LongHorizonMemoryBridgeError("latest verified checkpoint is not terminal-completed")
        if state.cursor.next_step_id or state.cursor.failed_step_ids or state.pending_approval_ids:
            raise LongHorizonMemoryBridgeError("completed checkpoint contains unresolved execution state")

        steps = list(self.store.list_mission_steps(mission_id))
        if len(steps) > self.MAX_STEPS:
            raise LongHorizonMemoryBridgeError("mission step count exceeds memory-ingestion limit")
        step_by_id = {self._clean(step.get("id")): step for step in steps if self._clean(step.get("id"))}
        if len(step_by_id) != len(steps):
            raise LongHorizonMemoryBridgeError("mission contains missing or duplicate step identities")

        checkpoint_completed = tuple(state.cursor.completed_step_ids)
        if len(checkpoint_completed) != len(set(checkpoint_completed)):
            raise LongHorizonMemoryBridgeError("checkpoint completed-step identities are not unique")
        persisted_completed = {
            step_id for step_id, step in step_by_id.items() if self._clean(step.get("status")).lower() == "completed"
        }
        if set(checkpoint_completed) != persisted_completed:
            raise LongHorizonMemoryBridgeError("checkpoint completion evidence disagrees with persisted mission steps")
        for step_id in checkpoint_completed:
            if step_id not in step_by_id:
                raise LongHorizonMemoryBridgeError("checkpoint references an unknown completed step")

        result = mission.get("result") or {}
        if not isinstance(result, dict):
            raise LongHorizonMemoryBridgeError("completed mission result is malformed")
        deterministic = self._review_verdict(result.get("deterministic_review"))
        security = self._review_verdict(result.get("security_review"))
        if deterministic != "pass":
            raise LongHorizonMemoryBridgeError("mission deterministic verification did not pass")
        if security == "fail" or not security:
            raise LongHorizonMemoryBridgeError("mission security verification is not acceptable")

        if len(state.evidence_ids) > self.MAX_EVIDENCE_IDS:
            raise LongHorizonMemoryBridgeError("mission evidence id count exceeds memory-ingestion limit")
        if len(state.artifact_refs) > self.MAX_ARTIFACT_REFS:
            raise LongHorizonMemoryBridgeError("mission artifact reference count exceeds memory-ingestion limit")
        if any(not self._clean(item) for item in state.evidence_ids):
            raise LongHorizonMemoryBridgeError("mission evidence ids cannot be empty")
        if any(not self._clean(item) for item in state.artifact_refs):
            raise LongHorizonMemoryBridgeError("mission artifact references cannot be empty")
        return mission, (checkpoint, state), steps

    @classmethod
    def _episode_content(cls, mission: dict[str, Any], checkpoint: dict[str, Any], state: Any, steps: list[dict[str, Any]]) -> str:
        step_summaries = [
            {
                "id": cls._clean(step.get("id")),
                "title": cls._bounded(step.get("title"), cls.MAX_STEP_TITLE_CHARS),
                "status": cls._clean(step.get("status")),
            }
            for step in steps
        ]
        payload = {
            "schema": "dpn-ai-v10-long-horizon-episode-1",
            "mission_id": cls._clean(mission.get("id")),
            "objective": cls._bounded(mission.get("objective"), cls.MAX_OBJECTIVE_CHARS),
            "status": "completed",
            "checkpoint_id": cls._clean(checkpoint.get("id")),
            "checkpoint_revision": int(state.revision),
            "completed_steps": step_summaries,
            "evidence_ids": list(state.evidence_ids),
            "artifact_refs": list(state.artifact_refs),
            "budget": {
                "elapsed_seconds": int(state.budget.elapsed_seconds),
                "tool_calls_used": int(state.budget.tool_calls_used),
                "max_seconds": int(state.budget.max_seconds),
                "max_tool_calls": int(state.budget.max_tool_calls),
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    async def promote_completed_mission(
        self,
        mission_id: str,
        *,
        context: MemoryContext | None = None,
        sensitive: bool = False,
    ) -> MissionMemoryPromotionResult:
        try:
            mission, verified, steps = self._validate_terminal_mission(mission_id)
        except LongHorizonMemoryBridgeError as exc:
            return MissionMemoryPromotionResult(mission_id=self._clean(mission_id), stored=False, reason=str(exc))

        checkpoint, state = verified
        memory_context = context or MemoryContext(
            project_id=self._clean(mission.get("project_id")) or None,
            conversation_id=self._clean(mission.get("conversation_id")) or None,
        )
        evidence_ids = tuple(self._clean(item) for item in state.evidence_ids)
        episode = self._episode_content(mission, checkpoint, state, steps)
        request = MemoryWriteRequest(
            layer=MemoryLayer.EPISODIC,
            key=f"long-horizon-mission:{self._clean(mission_id)}",
            content=episode,
            knowledge_class=KnowledgeClass.EPISODE,
            provenance=MemoryProvenance(
                source_type="long_horizon_mission",
                source_id=self._clean(checkpoint.get("id")) or self._clean(mission_id),
                evidence_ids=evidence_ids,
                confidence=1.0,
                authority=0.9,
            ),
            context=memory_context,
            sensitive=bool(sensitive),
        )
        result = await self.memory.remember(request)
        if not result.get("ok") or not result.get("stored"):
            return MissionMemoryPromotionResult(
                mission_id=self._clean(mission_id),
                stored=False,
                completed_step_count=len(steps),
                evidence_ids=evidence_ids,
                artifact_refs=tuple(self._clean(item) for item in state.artifact_refs),
                reason=self._clean(result.get("error")) or "episodic mission memory write failed",
            )
        return MissionMemoryPromotionResult(
            mission_id=self._clean(mission_id),
            stored=True,
            episodic_memory_id=self._clean(result.get("memory_id")),
            completed_step_count=len(steps),
            evidence_ids=evidence_ids,
            artifact_refs=tuple(self._clean(item) for item in state.artifact_refs),
            reason="verified completed long-horizon mission promoted to episodic memory",
        )


__all__ = [
    "LongHorizonMemoryBridge",
    "LongHorizonMemoryBridgeError",
    "MissionMemoryPromotionResult",
]
