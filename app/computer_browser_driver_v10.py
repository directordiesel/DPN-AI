from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class DriverContractError(ValueError):
    """Raised when desktop/browser driver evidence violates the v10 contract."""


class SurfaceKind(str, Enum):
    BROWSER = "browser"
    DESKTOP = "desktop"


class DriverAction(str, Enum):
    CLICK = "click"
    TYPE = "type"
    NAVIGATE = "navigate"
    FOCUS = "focus"
    SCROLL = "scroll"
    READ = "read"


@dataclass(frozen=True)
class ElementState:
    element_id: str
    text: str = ""
    value: str = ""
    enabled: bool = True
    visible: bool = True
    checked: bool | None = None

    def validate(self) -> None:
        if not self.element_id.strip():
            raise DriverContractError("element id is required")


@dataclass(frozen=True)
class DriverSnapshot:
    snapshot_id: str
    surface: SurfaceKind
    title: str = ""
    url: str = ""
    active_window: str = ""
    elements: tuple[ElementState, ...] = ()

    def validate(self) -> None:
        if not self.snapshot_id.strip():
            raise DriverContractError("snapshot id is required")
        seen: set[str] = set()
        for element in self.elements:
            element.validate()
            if element.element_id in seen:
                raise DriverContractError(f"duplicate element id: {element.element_id}")
            seen.add(element.element_id)

    def element(self, element_id: str) -> ElementState | None:
        return next((item for item in self.elements if item.element_id == element_id), None)


@dataclass(frozen=True)
class DriverCommand:
    action: DriverAction
    target_id: str = ""
    text: str = ""
    url: str = ""
    amount: int = 0

    def validate(self) -> None:
        if self.action in {DriverAction.CLICK, DriverAction.TYPE, DriverAction.FOCUS, DriverAction.READ} and not self.target_id.strip():
            raise DriverContractError("target id is required for element actions")
        if self.action == DriverAction.TYPE and self.text == "":
            raise DriverContractError("type action requires text payload")
        if self.action == DriverAction.NAVIGATE and not self.url.strip():
            raise DriverContractError("navigate action requires URL")
        if self.action == DriverAction.SCROLL and self.amount == 0:
            raise DriverContractError("scroll action requires non-zero amount")


@dataclass(frozen=True)
class DriverReceipt:
    command: DriverCommand
    accepted: bool
    before_snapshot_id: str
    after_snapshot_id: str = ""
    detail: str = ""

    def validate(self) -> None:
        self.command.validate()
        if not self.before_snapshot_id.strip():
            raise DriverContractError("before snapshot id is required")
        if self.accepted and not self.after_snapshot_id.strip():
            raise DriverContractError("accepted driver actions require an after snapshot id")


class VerificationKind(str, Enum):
    URL_EQUALS = "url_equals"
    URL_CONTAINS = "url_contains"
    TITLE_CONTAINS = "title_contains"
    WINDOW_EQUALS = "window_equals"
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_ENABLED = "element_enabled"
    ELEMENT_VALUE_EQUALS = "element_value_equals"
    ELEMENT_TEXT_CONTAINS = "element_text_contains"
    ELEMENT_CHECKED = "element_checked"


@dataclass(frozen=True)
class VerificationExpectation:
    kind: VerificationKind
    expected: str | bool
    target_id: str = ""

    def validate(self) -> None:
        element_kinds = {
            VerificationKind.ELEMENT_VISIBLE,
            VerificationKind.ELEMENT_ENABLED,
            VerificationKind.ELEMENT_VALUE_EQUALS,
            VerificationKind.ELEMENT_TEXT_CONTAINS,
            VerificationKind.ELEMENT_CHECKED,
        }
        if self.kind in element_kinds and not self.target_id.strip():
            raise DriverContractError("element verification requires target id")


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    failures: tuple[str, ...] = ()


@dataclass
class DriverSession:
    session_id: str
    surface: SurfaceKind
    max_recoveries: int = 2
    snapshots: list[DriverSnapshot] = field(default_factory=list)
    receipts: list[DriverReceipt] = field(default_factory=list)
    recoveries: int = 0

    def validate(self) -> None:
        if not self.session_id.strip():
            raise DriverContractError("session id is required")
        if isinstance(self.max_recoveries, bool) or not isinstance(self.max_recoveries, int) or not 0 <= self.max_recoveries <= 20:
            raise DriverContractError("max recoveries must be between 0 and 20")

    def record_snapshot(self, snapshot: DriverSnapshot) -> None:
        self.validate()
        snapshot.validate()
        if snapshot.surface != self.surface:
            raise DriverContractError("snapshot surface does not match session")
        if self.snapshots and self.snapshots[-1].snapshot_id == snapshot.snapshot_id:
            raise DriverContractError("snapshot id must advance after observation")
        self.snapshots.append(snapshot)

    def record_receipt(self, receipt: DriverReceipt) -> None:
        self.validate()
        receipt.validate()
        if not self.snapshots:
            raise DriverContractError("cannot record action without an observed snapshot")
        if receipt.before_snapshot_id != self.snapshots[-1].snapshot_id:
            raise DriverContractError("driver receipt must reference the latest pre-action snapshot")
        self.receipts.append(receipt)

    def record_recovery(self) -> None:
        if self.recoveries >= self.max_recoveries:
            raise DriverContractError("driver recovery budget exhausted")
        self.recoveries += 1


class DriverVerifier:
    @staticmethod
    def verify(snapshot: DriverSnapshot, expectations: Iterable[VerificationExpectation]) -> VerificationResult:
        snapshot.validate()
        materialized = list(expectations)
        if not materialized:
            raise DriverContractError("at least one verification expectation is required")

        failures: list[str] = []
        for expectation in materialized:
            expectation.validate()
            kind = expectation.kind
            expected = expectation.expected

            if kind == VerificationKind.URL_EQUALS and snapshot.url != str(expected):
                failures.append("url did not equal expected value")
            elif kind == VerificationKind.URL_CONTAINS and str(expected) not in snapshot.url:
                failures.append("url did not contain expected value")
            elif kind == VerificationKind.TITLE_CONTAINS and str(expected) not in snapshot.title:
                failures.append("title did not contain expected value")
            elif kind == VerificationKind.WINDOW_EQUALS and snapshot.active_window != str(expected):
                failures.append("active window did not equal expected value")
            elif kind in {
                VerificationKind.ELEMENT_VISIBLE,
                VerificationKind.ELEMENT_ENABLED,
                VerificationKind.ELEMENT_VALUE_EQUALS,
                VerificationKind.ELEMENT_TEXT_CONTAINS,
                VerificationKind.ELEMENT_CHECKED,
            }:
                element = snapshot.element(expectation.target_id)
                if element is None:
                    failures.append(f"missing element:{expectation.target_id}")
                    continue
                if kind == VerificationKind.ELEMENT_VISIBLE and element.visible != bool(expected):
                    failures.append(f"element visibility mismatch:{expectation.target_id}")
                elif kind == VerificationKind.ELEMENT_ENABLED and element.enabled != bool(expected):
                    failures.append(f"element enabled mismatch:{expectation.target_id}")
                elif kind == VerificationKind.ELEMENT_VALUE_EQUALS and element.value != str(expected):
                    failures.append(f"element value mismatch:{expectation.target_id}")
                elif kind == VerificationKind.ELEMENT_TEXT_CONTAINS and str(expected) not in element.text:
                    failures.append(f"element text mismatch:{expectation.target_id}")
                elif kind == VerificationKind.ELEMENT_CHECKED and element.checked != bool(expected):
                    failures.append(f"element checked mismatch:{expectation.target_id}")

        return VerificationResult(not failures, tuple(failures))


class DriverRecoveryPolicy:
    """Fail-closed recovery guidance for platform driver implementations.

    The policy never performs OS/browser actions itself. It decides whether a fresh
    observation/retry is allowed after failed verification and preserves a bounded
    recovery budget.
    """

    @staticmethod
    def can_retry(session: DriverSession, *, last_receipt: DriverReceipt, verification: VerificationResult) -> bool:
        session.validate()
        last_receipt.validate()
        if verification.passed:
            return False
        if not last_receipt.accepted:
            return False
        return session.recoveries < session.max_recoveries

    @staticmethod
    def require_fresh_post_action_snapshot(session: DriverSession, receipt: DriverReceipt) -> DriverSnapshot:
        if not receipt.accepted:
            raise DriverContractError("rejected action has no post-action verification snapshot")
        matches = [item for item in session.snapshots if item.snapshot_id == receipt.after_snapshot_id]
        if len(matches) != 1:
            raise DriverContractError("accepted action requires exactly one recorded post-action snapshot")
        return matches[0]


__all__ = [
    "DriverAction",
    "DriverCommand",
    "DriverContractError",
    "DriverReceipt",
    "DriverRecoveryPolicy",
    "DriverSession",
    "DriverSnapshot",
    "DriverVerifier",
    "ElementState",
    "SurfaceKind",
    "VerificationExpectation",
    "VerificationKind",
    "VerificationResult",
]
