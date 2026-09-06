from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.long_horizon_mission_runtime_v10 import (
    LongHorizonMissionError,
    LongHorizonMissionRuntime,
    MissionBudgetSnapshot,
    MissionCheckpointState,
    MissionCursor,
    MissionLifecycle,
    ResumeDisposition,
)


class MissionResumeError(LongHorizonMissionError):
    """Raised when a persisted mission cannot be resumed safely."""


@dataclass(frozen=True)
class ResumeExecutionResult:
    mission_id: str
    status: str
    resumed_from_checkpoint_id: str
    executed_step_ids: tuple[str, ...]
    skipped_completed_step_ids: tuple[str, ...]
    tool_calls_used: int
    elapsed_seconds: int
    message: str


class MissionResumeCoordinator:
    """Execute only the unfinished portion of an existing persisted mission.

    This coordinator deliberately reuses MissionOrchestrator._execute_step and
    MissionOrchestrator.review. It does not create a second tool/provider execution
    path. The verified v10 checkpoint is authoritative for the resume cursor and
    cumulative budget. Completed steps are never replayed.
    """

    def __init__(self, orchestrator: Any) -> None:
        required = ("db", "agent", "cognitive", "_execute_step", "review")
        if any(not hasattr(orchestrator, name) for name in required):
            raise MissionResumeError("orchestrator does not expose the required mission execution contract")
        self.orchestrator = orchestrator
        self.db = orchestrator.db
        self.runtime = LongHorizonMissionRuntime(self.db)

    @staticmethod
    def _unique(values: list[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if value))

    def _collect_evidence(self, mission_id: str) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
        evidence: list[dict[str, Any]] = []
        evidence_ids: list[str] = []
        artifact_refs: list[str] = []
        for step in self.db.list_mission_steps(mission_id):
            result = step.get("result") or {}
            if step.get("status") == "completed":
                item = {"step": step.get("title", ""), **result}
                evidence.append(item)
                run_id = str(result.get("run_id") or "").strip()
                if run_id:
                    evidence_ids.append(run_id)
                artifact_refs.extend(str(path) for path in result.get("generated_files", []) if str(path).strip())
        return evidence, self._unique(evidence_ids), self._unique(artifact_refs)

    def _checkpoint(
        self,
        mission_id: str,
        *,
        lifecycle: MissionLifecycle,
        next_step_id: str,
        elapsed_seconds: int,
        tool_calls_used: int,
        max_seconds: int,
        max_tool_calls: int,
        reason: str,
        revision: int,
        step_id: str | None = None,
    ) -> dict[str, Any]:
        steps = self.db.list_mission_steps(mission_id)
        completed = tuple(str(step["id"]) for step in steps if step.get("status") == "completed")
        failed = tuple(str(step["id"]) for step in steps if step.get("status") == "failed")
        _evidence, evidence_ids, artifact_refs = self._collect_evidence(mission_id)
        state = MissionCheckpointState(
            schema_version=1,
            lifecycle=lifecycle,
            cursor=MissionCursor(
                mission_id=mission_id,
                next_step_id=next_step_id,
                completed_step_ids=completed,
                failed_step_ids=failed,
                attempt=sum(int(step.get("attempts") or 0) for step in steps),
            ),
            budget=MissionBudgetSnapshot(
                elapsed_seconds=max(0, int(elapsed_seconds)),
                tool_calls_used=max(0, int(tool_calls_used)),
                max_seconds=max_seconds,
                max_tool_calls=max_tool_calls,
            ),
            evidence_ids=evidence_ids,
            artifact_refs=artifact_refs,
            reason=reason,
            revision=revision,
        )
        return self.runtime.checkpoint(state, step_id=step_id)

    async def resume(
        self,
        mission_id: str,
        *,
        attachments: list[str] | None = None,
        think: bool | str | None = None,
    ) -> ResumeExecutionResult:
        decision = self.runtime.recovery_decision(mission_id)
        if decision.disposition == ResumeDisposition.STOP:
            raise MissionResumeError(decision.reason)
        if decision.disposition == ResumeDisposition.REPLAN:
            raise MissionResumeError("mission requires replanning before it can be resumed")

        latest = self.runtime.latest_verified(mission_id)
        if latest is None:
            raise MissionResumeError("no verified long-horizon checkpoint is available")
        checkpoint, state = latest
        mission = self.db.get_mission(mission_id)
        if mission is None:
            raise MissionResumeError("mission no longer exists")

        steps = self.db.list_mission_steps(mission_id)
        step_by_id = {str(step["id"]): step for step in steps}
        if state.cursor.next_step_id and state.cursor.next_step_id not in step_by_id:
            raise MissionResumeError("verified checkpoint references a missing next step")

        completed_ids = set(state.cursor.completed_step_ids)
        for step_id in completed_ids:
            persisted = step_by_id.get(step_id)
            if not persisted or persisted.get("status") != "completed":
                raise MissionResumeError("checkpoint completion evidence disagrees with persisted mission-step state")

        budget = mission.get("budget") or {}
        max_seconds = int(state.budget.max_seconds)
        max_tool_calls = int(state.budget.max_tool_calls)
        if max_seconds < 1 or max_tool_calls < 1:
            raise MissionResumeError("persisted mission budget is invalid")

        effective = self.orchestrator.agent.effective_settings()
        worker_model = str(mission.get("worker_model") or effective.get("worker_model") or effective.get("model") or "").strip()
        reviewer_model = str(mission.get("reviewer_model") or worker_model).strip()
        if not worker_model or not reviewer_model:
            raise MissionResumeError("persisted mission model identity is incomplete")
        selected_think = effective.get("think_level", "medium") if think is None else think
        conversation_id = str(mission.get("conversation_id") or "").strip()
        if not conversation_id:
            conversation_id = self.db.ensure_conversation(None, str(mission.get("objective") or "Resumed mission"))
        project_id = mission.get("project_id")
        objective = str(mission.get("objective") or "").strip()
        if not objective:
            raise MissionResumeError("persisted mission objective is missing")
        contract = self.orchestrator.cognitive.derive_contract(objective)

        start_index = 0
        if state.cursor.next_step_id:
            start_index = next(
                (index for index, step in enumerate(steps) if str(step["id"]) == state.cursor.next_step_id),
                len(steps),
            )
        else:
            start_index = next(
                (index for index, step in enumerate(steps) if str(step["id"]) not in completed_ids),
                len(steps),
            )

        mission_started = time.monotonic()
        prior_elapsed = int(state.budget.elapsed_seconds)
        total_tool_calls = int(state.budget.tool_calls_used)
        revision = int(state.revision) + 1
        executed: list[str] = []
        skipped = [str(step["id"]) for step in steps if str(step["id"]) in completed_ids]
        self.db.update_mission(mission_id, "running")

        for index in range(start_index, len(steps)):
            step = self.db.get_mission_step(str(steps[index]["id"])) or steps[index]
            step_id = str(step["id"])
            if step_id in completed_ids or step.get("status") == "completed":
                continue
            elapsed = prior_elapsed + int(time.monotonic() - mission_started)
            if elapsed >= max_seconds or total_tool_calls >= max_tool_calls:
                self.db.update_mission_step(step_id, "blocked", {"reason": "Persisted mission budget reached during resume"})
                self.db.update_mission(mission_id, "paused")
                self._checkpoint(
                    mission_id,
                    lifecycle=MissionLifecycle.PAUSED,
                    next_step_id=step_id,
                    elapsed_seconds=elapsed,
                    tool_calls_used=total_tool_calls,
                    max_seconds=max_seconds,
                    max_tool_calls=max_tool_calls,
                    reason="resume paused because cumulative mission budget was reached",
                    revision=revision,
                    step_id=step_id,
                )
                raise MissionResumeError("cumulative mission budget reached during resume")

            dependencies = [self.db.get_mission_step(dep) for dep in step.get("dependencies", [])]
            if any(not dep or dep.get("status") != "completed" for dep in dependencies):
                self.db.update_mission_step(step_id, "blocked", {"reason": "Dependency did not complete before resume"})
                self.db.update_mission(mission_id, "blocked")
                self._checkpoint(
                    mission_id,
                    lifecycle=MissionLifecycle.BLOCKED,
                    next_step_id=step_id,
                    elapsed_seconds=elapsed,
                    tool_calls_used=total_tool_calls,
                    max_seconds=max_seconds,
                    max_tool_calls=max_tool_calls,
                    reason="resume blocked by incomplete dependency",
                    revision=revision,
                    step_id=step_id,
                )
                raise MissionResumeError("resume blocked by incomplete dependency")

            planned = step.get("result") or {}
            step["evidence_required"] = planned.get("evidence_required", [])
            step["max_attempts"] = max(1, min(int(planned.get("max_attempts", 2)), 5))
            step["rollback"] = planned.get("rollback", "")
            self._checkpoint(
                mission_id,
                lifecycle=MissionLifecycle.RECOVERING if decision.disposition == ResumeDisposition.REPAIR else MissionLifecycle.RUNNING,
                next_step_id=step_id,
                elapsed_seconds=elapsed,
                tool_calls_used=total_tool_calls,
                max_seconds=max_seconds,
                max_tool_calls=max_tool_calls,
                reason="about to execute next persisted mission step after restart",
                revision=revision,
                step_id=step_id,
            )
            revision += 1

            completed = False
            last_error = ""
            for _attempt in range(1, step["max_attempts"] + 1):
                self.db.update_mission_step(step_id, "running", increment_attempts=True)
                try:
                    result, tool_count = await self.orchestrator._execute_step(
                        mission_id,
                        objective,
                        contract,
                        step,
                        conversation_id,
                        project_id,
                        attachments or [],
                        selected_think,
                        worker_model,
                        effective,
                    )
                    total_tool_calls += int(tool_count)
                    result["resumed"] = True
                    self.db.update_mission_step(step_id, "completed", result)
                    completed_ids.add(step_id)
                    executed.append(step_id)
                    next_step_id = next(
                        (str(candidate["id"]) for candidate in steps[index + 1 :] if str(candidate["id"]) not in completed_ids),
                        "",
                    )
                    elapsed = prior_elapsed + int(time.monotonic() - mission_started)
                    self._checkpoint(
                        mission_id,
                        lifecycle=MissionLifecycle.RUNNING,
                        next_step_id=next_step_id,
                        elapsed_seconds=elapsed,
                        tool_calls_used=total_tool_calls,
                        max_seconds=max_seconds,
                        max_tool_calls=max_tool_calls,
                        reason=f"resumed step {step_id} completed and execution cursor advanced",
                        revision=revision,
                        step_id=step_id,
                    )
                    revision += 1
                    completed = True
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"
            if not completed:
                self.db.update_mission_step(step_id, "failed", {"error": last_error, "rollback": step.get("rollback", "")})
                elapsed = prior_elapsed + int(time.monotonic() - mission_started)
                self.db.update_mission(mission_id, "blocked")
                self._checkpoint(
                    mission_id,
                    lifecycle=MissionLifecycle.RECOVERING,
                    next_step_id=step_id,
                    elapsed_seconds=elapsed,
                    tool_calls_used=total_tool_calls,
                    max_seconds=max_seconds,
                    max_tool_calls=max_tool_calls,
                    reason=f"resumed step failed after bounded retries: {last_error}",
                    revision=revision,
                    step_id=step_id,
                )
                raise MissionResumeError(last_error or "resumed mission step failed")

        evidence, _evidence_ids, _artifact_refs = self._collect_evidence(mission_id)
        deterministic = self.orchestrator.cognitive.verify_evidence(evidence, contract)
        deterministic["evaluator"] = "deterministic"
        self.db.add_evaluation(
            mission_id,
            "deterministic-resume",
            deterministic["verdict"],
            float(deterministic.get("confidence", 0.0)),
            deterministic,
        )
        review = await self.orchestrator.review(contract, evidence, reviewer_model, selected_think, "security")
        self.db.add_evaluation(
            mission_id,
            "security-resume",
            review["verdict"],
            float(review.get("confidence", 0.0)),
            review,
        )
        final_ok = deterministic.get("verdict") == "pass" and review.get("verdict") != "fail"
        status = "completed" if final_ok else "blocked"
        elapsed = prior_elapsed + int(time.monotonic() - mission_started)
        final_result = {
            "resumed": True,
            "resumed_from_checkpoint_id": str(checkpoint.get("id") or ""),
            "evidence": evidence,
            "deterministic_review": deterministic,
            "security_review": review,
            "usage": {
                "tool_calls": total_tool_calls,
                "elapsed_seconds": elapsed,
                "budget": {**budget, "max_seconds": max_seconds, "max_tool_calls": max_tool_calls},
            },
        }
        self.db.update_mission(mission_id, status, final_result)
        lifecycle = MissionLifecycle.COMPLETED if final_ok else MissionLifecycle.BLOCKED
        self._checkpoint(
            mission_id,
            lifecycle=lifecycle,
            next_step_id="",
            elapsed_seconds=elapsed,
            tool_calls_used=total_tool_calls,
            max_seconds=max_seconds,
            max_tool_calls=max_tool_calls,
            reason="resumed mission completed verification" if final_ok else "resumed mission requires additional repair or review",
            revision=revision,
        )
        message = "Mission resumed from its verified checkpoint and completed." if final_ok else "Mission resumed safely but did not pass final verification."
        return ResumeExecutionResult(
            mission_id=mission_id,
            status=status,
            resumed_from_checkpoint_id=str(checkpoint.get("id") or ""),
            executed_step_ids=tuple(executed),
            skipped_completed_step_ids=tuple(skipped),
            tool_calls_used=total_tool_calls,
            elapsed_seconds=elapsed,
            message=message,
        )


__all__ = ["MissionResumeCoordinator", "MissionResumeError", "ResumeExecutionResult"]
