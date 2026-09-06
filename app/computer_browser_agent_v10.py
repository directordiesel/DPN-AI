from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class ComputerAgentError(ValueError):
    """Raised when computer/browser agent evidence violates the runtime contract."""


class SurfaceKind(str, Enum):
    DESKTOP = "desktop"
    BROWSER = "browser"
    TERMINAL = "terminal"


class ActionKind(str, Enum):
    CLICK = "click"
    TYPE = "type"
    NAVIGATE = "navigate"
    SCROLL = "scroll"
    KEY = "key"
    WAIT = "wait"
    READ = "read"


class ActionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ScreenElement:
    element_id: str
    role: str
    label: str = ""
    text: str = ""
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    enabled: bool = True

    def validate(self) -> None:
        if not self.element_id.strip():
            raise ComputerAgentError("screen element id is required")
        if not self.role.strip():
            raise ComputerAgentError("screen element role is required")
        dims = (self.x, self.y, self.width, self.height)
        if any(value is not None and value < 0 for value in dims):
            raise ComputerAgentError("screen element geometry must be non-negative")


@dataclass(frozen=True)
class SurfaceObservation:
    surface: SurfaceKind
    title: str
    url: str = ""
    elements: tuple[ScreenElement, ...] = ()
    screenshot_ref: str = ""
    sequence: int = 0

    def validate(self) -> None:
        if not self.title.strip():
            raise ComputerAgentError("surface title is required")
        if self.sequence < 0:
            raise ComputerAgentError("observation sequence must be non-negative")
        seen: set[str] = set()
        for element in self.elements:
            element.validate()
            if element.element_id in seen:
                raise ComputerAgentError(f"duplicate screen element id: {element.element_id}")
            seen.add(element.element_id)


@dataclass(frozen=True)
class ComputerAction:
    kind: ActionKind
    target_id: str = ""
    value: str = ""
    risk: ActionRisk = ActionRisk.LOW
    destructive: bool = False
    reason: str = ""

    def validate(self) -> None:
        if self.kind in {ActionKind.CLICK, ActionKind.TYPE, ActionKind.READ} and not self.target_id.strip():
            raise ComputerAgentError(f"{self.kind.value} action requires target id")
        if self.kind in {ActionKind.TYPE, ActionKind.NAVIGATE, ActionKind.KEY} and not self.value:
            raise ComputerAgentError(f"{self.kind.value} action requires a value")
        if not self.reason.strip():
            raise ComputerAgentError("computer action reason is required")


@dataclass(frozen=True)
class ActionPolicyDecision:
    allowed: bool
    approval_required: bool
    reason: str


@dataclass(frozen=True)
class ActionEvidence:
    action: ComputerAction
    before_sequence: int
    after_sequence: int
    observed_change: bool
    success: bool
    detail: str = ""

    def validate(self) -> None:
        self.action.validate()
        if self.before_sequence < 0 or self.after_sequence < 0:
            raise ComputerAgentError("action evidence sequences must be non-negative")
        if self.after_sequence < self.before_sequence:
            raise ComputerAgentError("action evidence sequence cannot move backwards")


@dataclass
class ComputerMission:
    mission_id: str
    objective: str
    max_corrections: int = 3
    corrections: int = 0
    observations: list[SurfaceObservation] = field(default_factory=list)
    evidence: list[ActionEvidence] = field(default_factory=list)
    completed: bool = False
    failure_reason: str = ""

    def validate(self) -> None:
        if not self.mission_id.strip():
            raise ComputerAgentError("computer mission id is required")
        if not self.objective.strip():
            raise ComputerAgentError("computer mission objective is required")
        if isinstance(self.max_corrections, bool) or not isinstance(self.max_corrections, int) or not 0 <= self.max_corrections <= 20:
            raise ComputerAgentError("max corrections must be between 0 and 20")

    def observe(self, observation: SurfaceObservation) -> None:
        observation.validate()
        if self.observations and observation.sequence <= self.observations[-1].sequence:
            raise ComputerAgentError("observation sequence must increase")
        self.observations.append(observation)

    def record_evidence(self, evidence: ActionEvidence) -> None:
        evidence.validate()
        self.evidence.append(evidence)

    def record_correction(self) -> None:
        if self.corrections >= self.max_corrections:
            self.fail("correction budget exhausted")
            raise ComputerAgentError("correction budget exhausted")
        self.corrections += 1

    def complete(self) -> None:
        if not self.evidence or not self.evidence[-1].success:
            raise ComputerAgentError("mission cannot complete without successful action evidence")
        self.completed = True

    def fail(self, reason: str) -> None:
        if not reason.strip():
            raise ComputerAgentError("failure reason is required")
        self.failure_reason = reason.strip()
        self.completed = False


class ComputerActionPolicy:
    """Fail-closed policy for browser/desktop actions.

    Low/medium non-destructive actions may proceed. High-risk and destructive
    actions require explicit approval. Critical actions are denied by this
    foundation runtime until a stronger approval contract is provided.
    """

    @staticmethod
    def evaluate(action: ComputerAction, *, approval_granted: bool = False) -> ActionPolicyDecision:
        action.validate()
        if action.risk == ActionRisk.CRITICAL:
            return ActionPolicyDecision(False, True, "critical computer action is denied by default")
        if action.destructive or action.risk == ActionRisk.HIGH:
            if not approval_granted:
                return ActionPolicyDecision(False, True, "high-risk or destructive computer action requires approval")
            return ActionPolicyDecision(True, False, "approved high-risk action")
        return ActionPolicyDecision(True, False, "action permitted by bounded computer policy")


class ComputerBrowserAgentRuntime:
    """Governed observe/act/verify/correct foundation for DPN AI v10.

    This module records intent, observations, policy decisions and evidence. It
    does not itself drive a browser or desktop; platform drivers must execute
    approved actions and return fresh observations for verification.
    """

    @staticmethod
    def select_target(observation: SurfaceObservation, *, role: str = "", text: str = "", label: str = "") -> ScreenElement:
        observation.validate()
        candidates = []
        for element in observation.elements:
            if role and element.role.lower() != role.lower():
                continue
            haystack = " ".join((element.label, element.text)).lower()
            if text and text.lower() not in haystack:
                continue
            if label and label.lower() not in element.label.lower():
                continue
            if not element.enabled:
                continue
            candidates.append(element)
        if not candidates:
            raise ComputerAgentError("no enabled screen element satisfies target criteria")
        if len(candidates) > 1:
            raise ComputerAgentError("target criteria are ambiguous")
        return candidates[0]

    @staticmethod
    def verify_action(before: SurfaceObservation, after: SurfaceObservation, action: ComputerAction, *, expected_text: str = "") -> ActionEvidence:
        before.validate()
        after.validate()
        action.validate()
        if after.sequence <= before.sequence:
            raise ComputerAgentError("post-action observation must be newer than pre-action observation")
        changed = before != after
        success = changed
        detail = "surface changed after action" if changed else "no observable surface change"
        if expected_text:
            text_blob = " ".join(" ".join((item.label, item.text)) for item in after.elements).lower()
            success = expected_text.lower() in text_blob
            detail = f"expected text {'observed' if success else 'not observed'}: {expected_text}"
        return ActionEvidence(action, before.sequence, after.sequence, changed, success, detail)

    @staticmethod
    def route_after_verification(mission: ComputerMission, evidence: ActionEvidence) -> str:
        mission.record_evidence(evidence)
        if evidence.success:
            return "continue"
        if mission.corrections >= mission.max_corrections:
            mission.fail("computer action verification failed and correction budget is exhausted")
            return "failed"
        mission.record_correction()
        return "correct"


__all__ = [
    "ActionEvidence",
    "ActionKind",
    "ActionPolicyDecision",
    "ActionRisk",
    "ComputerAction",
    "ComputerActionPolicy",
    "ComputerAgentError",
    "ComputerBrowserAgentRuntime",
    "ComputerMission",
    "ScreenElement",
    "SurfaceKind",
    "SurfaceObservation",
]
