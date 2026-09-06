from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.computer_browser_adapters_v10 import AdapterExecutionReceipt, PlatformAdapter
from app.computer_browser_agent_v10 import (
    ActionEvidence,
    ActionKind,
    ComputerAction,
    ComputerActionPolicy,
    ComputerAgentError,
    ComputerMission,
    SurfaceObservation,
)
from app.computer_browser_driver_v10 import (
    DriverAction,
    DriverCommand,
    DriverContractError,
    DriverRecoveryPolicy,
    DriverSession,
    DriverSnapshot,
    DriverVerifier,
    VerificationExpectation,
    VerificationResult,
)


class ComputerCoordinatorError(ValueError):
    """Raised when an end-to-end computer/browser mission violates its contract."""


@dataclass(frozen=True)
class ComputerStepResult:
    accepted: bool
    verified: bool
    route: str
    adapter_receipt: AdapterExecutionReceipt | None
    verification: VerificationResult | None
    evidence: ActionEvidence | None
    reason: str


@dataclass(frozen=True)
class ComputerMissionResult:
    mission_id: str
    completed: bool
    corrections: int
    actions_recorded: int
    driver_receipts: int
    failure_reason: str = ""


class ComputerBrowserMissionCoordinator:
    """Governed end-to-end coordinator for Batch 3.

    The coordinator connects mission intent, policy, concrete adapter execution,
    driver-level verification, and bounded correction behavior. It never invents
    an execution result or post-action observation.
    """

    _driver_action = {
        ActionKind.CLICK: DriverAction.CLICK,
        ActionKind.TYPE: DriverAction.TYPE,
        ActionKind.NAVIGATE: DriverAction.NAVIGATE,
        ActionKind.SCROLL: DriverAction.SCROLL,
        ActionKind.READ: DriverAction.READ,
    }

    def __init__(self, mission: ComputerMission, session: DriverSession, adapter: PlatformAdapter) -> None:
        mission.validate()
        session.validate()
        if session.surface != adapter.descriptor.surface:
            raise ComputerCoordinatorError("driver session surface must match adapter surface")
        self.mission = mission
        self.session = session
        self.adapter = adapter

    def accept_initial_state(self, *, observation: SurfaceObservation, snapshot: DriverSnapshot) -> None:
        if self.mission.observations:
            raise ComputerCoordinatorError("initial mission state has already been recorded")
        self.mission.observe(observation)
        self.adapter.accept_snapshot(self.session, snapshot)

    @classmethod
    def _to_driver_command(cls, action: ComputerAction) -> DriverCommand:
        action.validate()
        if action.kind not in cls._driver_action:
            raise ComputerCoordinatorError(f"unsupported coordinated action kind: {action.kind.value}")
        driver_action = cls._driver_action[action.kind]
        if driver_action == DriverAction.TYPE:
            return DriverCommand(action=driver_action, target_id=action.target_id, text=action.value)
        if driver_action == DriverAction.NAVIGATE:
            return DriverCommand(action=driver_action, url=action.value)
        if driver_action == DriverAction.SCROLL:
            try:
                amount = int(action.value)
            except (TypeError, ValueError) as exc:
                raise ComputerCoordinatorError("scroll action value must be an integer") from exc
            return DriverCommand(action=driver_action, amount=amount)
        return DriverCommand(action=driver_action, target_id=action.target_id)

    def execute_step(
        self,
        *,
        action: ComputerAction,
        after_observation: SurfaceObservation | None,
        after_snapshot: DriverSnapshot | None,
        expectations: Iterable[VerificationExpectation],
        approval_granted: bool = False,
    ) -> ComputerStepResult:
        if self.mission.completed or self.mission.failure_reason:
            raise ComputerCoordinatorError("cannot execute actions after mission termination")
        if not self.mission.observations or not self.session.snapshots:
            raise ComputerCoordinatorError("mission requires an initial observation and driver snapshot")

        decision = ComputerActionPolicy.evaluate(action, approval_granted=approval_granted)
        if not decision.allowed:
            return ComputerStepResult(False, False, "blocked", None, None, None, decision.reason)

        command = self._to_driver_command(action)
        try:
            receipt = self.adapter.build_execution_receipt(
                self.session,
                command,
                after_snapshot=after_snapshot,
                approval_granted=approval_granted,
            )
        except DriverContractError as exc:
            raise ComputerCoordinatorError(str(exc)) from exc

        if not receipt.accepted:
            return ComputerStepResult(False, False, "blocked", receipt, None, None, receipt.reason)
        if after_observation is None or after_snapshot is None:
            raise ComputerCoordinatorError("accepted execution requires both agent and driver post-action observations")

        before_observation = self.mission.observations[-1]
        self.mission.observe(after_observation)

        materialized = tuple(expectations)
        try:
            verification = DriverVerifier.verify(after_snapshot, materialized)
        except DriverContractError as exc:
            raise ComputerCoordinatorError(str(exc)) from exc

        agent_evidence = ActionEvidence(
            action=action,
            before_sequence=before_observation.sequence,
            after_sequence=after_observation.sequence,
            observed_change=before_observation != after_observation,
            success=verification.passed,
            detail="driver verification passed" if verification.passed else "; ".join(verification.failures),
        )

        route = self._route_verification(receipt=receipt, verification=verification, evidence=agent_evidence)
        return ComputerStepResult(
            accepted=True,
            verified=verification.passed,
            route=route,
            adapter_receipt=receipt,
            verification=verification,
            evidence=agent_evidence,
            reason=agent_evidence.detail,
        )

    def _route_verification(
        self,
        *,
        receipt: AdapterExecutionReceipt,
        verification: VerificationResult,
        evidence: ActionEvidence,
    ) -> str:
        self.mission.record_evidence(evidence)
        if verification.passed:
            return "continue"

        driver_receipt = self.session.receipts[-1]
        if not DriverRecoveryPolicy.can_retry(
            self.session,
            last_receipt=driver_receipt,
            verification=verification,
        ):
            self.mission.fail("computer/browser verification failed and driver recovery is unavailable")
            return "failed"

        if self.mission.corrections >= self.mission.max_corrections:
            self.mission.fail("computer/browser verification failed and correction budget is exhausted")
            return "failed"

        self.session.record_recovery()
        self.mission.record_correction()
        return "correct"

    def complete(self) -> ComputerMissionResult:
        if self.mission.failure_reason:
            return self.result()
        if not self.mission.evidence or not self.mission.evidence[-1].success:
            raise ComputerCoordinatorError("mission cannot complete without final verified evidence")
        self.mission.complete()
        return self.result()

    def result(self) -> ComputerMissionResult:
        return ComputerMissionResult(
            mission_id=self.mission.mission_id,
            completed=self.mission.completed,
            corrections=self.mission.corrections,
            actions_recorded=len(self.mission.evidence),
            driver_receipts=len(self.session.receipts),
            failure_reason=self.mission.failure_reason,
        )


__all__ = [
    "ComputerBrowserMissionCoordinator",
    "ComputerCoordinatorError",
    "ComputerMissionResult",
    "ComputerStepResult",
]
