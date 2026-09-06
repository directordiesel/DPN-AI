from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.computer_browser_driver_v10 import (
    DriverAction,
    DriverCommand,
    DriverContractError,
    DriverReceipt,
    DriverSession,
    DriverSnapshot,
    SurfaceKind,
)


class AdapterHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AdapterCapability(str, Enum):
    OBSERVE = "observe"
    CLICK = "click"
    TYPE = "type"
    NAVIGATE = "navigate"
    FOCUS = "focus"
    SCROLL = "scroll"
    READ = "read"
    SCREENSHOT = "screenshot"
    WINDOW_ENUMERATION = "window_enumeration"
    URL_STATE = "url_state"


@dataclass(frozen=True)
class AdapterDescriptor:
    adapter_id: str
    surface: SurfaceKind
    capabilities: tuple[AdapterCapability, ...]
    health: AdapterHealth = AdapterHealth.HEALTHY
    detail: str = ""

    def validate(self) -> None:
        if not self.adapter_id.strip():
            raise DriverContractError("adapter id is required")
        if not self.capabilities:
            raise DriverContractError("adapter must advertise at least one capability")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise DriverContractError("adapter capabilities must be unique")

    def supports(self, capability: AdapterCapability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class ExecutionPolicy:
    allowed_capabilities: tuple[AdapterCapability, ...]
    approval_required_actions: tuple[DriverAction, ...] = ()

    def validate(self) -> None:
        if len(set(self.allowed_capabilities)) != len(self.allowed_capabilities):
            raise DriverContractError("allowed capabilities must be unique")
        if len(set(self.approval_required_actions)) != len(self.approval_required_actions):
            raise DriverContractError("approval-required actions must be unique")


@dataclass(frozen=True)
class AdapterExecutionReceipt:
    adapter_id: str
    command: DriverCommand
    accepted: bool
    before_snapshot_id: str
    after_snapshot_id: str = ""
    reason: str = ""
    approval_used: bool = False

    def validate(self) -> None:
        if not self.adapter_id.strip():
            raise DriverContractError("adapter execution receipt requires adapter id")
        DriverReceipt(
            command=self.command,
            accepted=self.accepted,
            before_snapshot_id=self.before_snapshot_id,
            after_snapshot_id=self.after_snapshot_id,
            detail=self.reason,
        ).validate()


class AdapterExecutionGate:
    _capability_for_action = {
        DriverAction.CLICK: AdapterCapability.CLICK,
        DriverAction.TYPE: AdapterCapability.TYPE,
        DriverAction.NAVIGATE: AdapterCapability.NAVIGATE,
        DriverAction.FOCUS: AdapterCapability.FOCUS,
        DriverAction.SCROLL: AdapterCapability.SCROLL,
        DriverAction.READ: AdapterCapability.READ,
    }

    @classmethod
    def authorize(
        cls,
        descriptor: AdapterDescriptor,
        policy: ExecutionPolicy,
        command: DriverCommand,
        *,
        approval_granted: bool = False,
    ) -> tuple[bool, str]:
        descriptor.validate()
        policy.validate()
        command.validate()

        if descriptor.health == AdapterHealth.UNAVAILABLE:
            return False, "adapter is unavailable"

        required = cls._capability_for_action[command.action]
        if not descriptor.supports(required):
            return False, f"adapter does not support {required.value}"
        if required not in policy.allowed_capabilities:
            return False, f"policy does not allow {required.value}"
        if command.action in policy.approval_required_actions and not approval_granted:
            return False, f"{command.action.value} requires approval"
        return True, "authorized"


class PlatformAdapter:
    """Deterministic platform adapter contract for v10 computer/browser control.

    Real implementations may wrap Playwright, WebDriver, Windows UI Automation, or
    another governed backend. The base contract never fabricates observations or
    execution success; callers must supply concrete post-action evidence.
    """

    def __init__(self, descriptor: AdapterDescriptor, policy: ExecutionPolicy) -> None:
        descriptor.validate()
        policy.validate()
        self.descriptor = descriptor
        self.policy = policy

    def require_observation_capability(self) -> None:
        if self.descriptor.health == AdapterHealth.UNAVAILABLE:
            raise DriverContractError("adapter is unavailable")
        if not self.descriptor.supports(AdapterCapability.OBSERVE):
            raise DriverContractError("adapter does not support observations")
        if AdapterCapability.OBSERVE not in self.policy.allowed_capabilities:
            raise DriverContractError("observation is denied by policy")

    def accept_snapshot(self, session: DriverSession, snapshot: DriverSnapshot) -> None:
        self.require_observation_capability()
        if snapshot.surface != self.descriptor.surface:
            raise DriverContractError("adapter snapshot surface mismatch")
        session.record_snapshot(snapshot)

    def build_execution_receipt(
        self,
        session: DriverSession,
        command: DriverCommand,
        *,
        after_snapshot: DriverSnapshot | None,
        approval_granted: bool = False,
        rejection_reason: str = "",
    ) -> AdapterExecutionReceipt:
        if not session.snapshots:
            raise DriverContractError("adapter execution requires a current observation")
        if session.surface != self.descriptor.surface:
            raise DriverContractError("session surface does not match adapter")

        authorized, reason = AdapterExecutionGate.authorize(
            self.descriptor,
            self.policy,
            command,
            approval_granted=approval_granted,
        )
        before = session.snapshots[-1]
        if not authorized:
            return AdapterExecutionReceipt(
                adapter_id=self.descriptor.adapter_id,
                command=command,
                accepted=False,
                before_snapshot_id=before.snapshot_id,
                reason=rejection_reason.strip() or reason,
                approval_used=False,
            )

        if after_snapshot is None:
            raise DriverContractError("authorized execution requires concrete post-action observation")
        if after_snapshot.surface != session.surface:
            raise DriverContractError("post-action snapshot surface mismatch")
        if after_snapshot.snapshot_id == before.snapshot_id:
            raise DriverContractError("post-action snapshot id must be fresh")

        receipt = AdapterExecutionReceipt(
            adapter_id=self.descriptor.adapter_id,
            command=command,
            accepted=True,
            before_snapshot_id=before.snapshot_id,
            after_snapshot_id=after_snapshot.snapshot_id,
            reason="executed with post-action evidence",
            approval_used=command.action in self.policy.approval_required_actions,
        )
        session.record_receipt(
            DriverReceipt(
                command=command,
                accepted=True,
                before_snapshot_id=before.snapshot_id,
                after_snapshot_id=after_snapshot.snapshot_id,
                detail=receipt.reason,
            )
        )
        session.record_snapshot(after_snapshot)
        return receipt


class BrowserAdapter(PlatformAdapter):
    @classmethod
    def default(cls, adapter_id: str = "browser") -> "BrowserAdapter":
        descriptor = AdapterDescriptor(
            adapter_id=adapter_id,
            surface=SurfaceKind.BROWSER,
            capabilities=(
                AdapterCapability.OBSERVE,
                AdapterCapability.CLICK,
                AdapterCapability.TYPE,
                AdapterCapability.NAVIGATE,
                AdapterCapability.FOCUS,
                AdapterCapability.SCROLL,
                AdapterCapability.READ,
                AdapterCapability.SCREENSHOT,
                AdapterCapability.URL_STATE,
            ),
        )
        return cls(descriptor, ExecutionPolicy(allowed_capabilities=descriptor.capabilities))


class WindowsDesktopAdapter(PlatformAdapter):
    @classmethod
    def default(cls, adapter_id: str = "windows-desktop") -> "WindowsDesktopAdapter":
        descriptor = AdapterDescriptor(
            adapter_id=adapter_id,
            surface=SurfaceKind.DESKTOP,
            capabilities=(
                AdapterCapability.OBSERVE,
                AdapterCapability.CLICK,
                AdapterCapability.TYPE,
                AdapterCapability.FOCUS,
                AdapterCapability.SCROLL,
                AdapterCapability.READ,
                AdapterCapability.SCREENSHOT,
                AdapterCapability.WINDOW_ENUMERATION,
            ),
        )
        return cls(
            descriptor,
            ExecutionPolicy(
                allowed_capabilities=descriptor.capabilities,
                approval_required_actions=(),
            ),
        )


__all__ = [
    "AdapterCapability",
    "AdapterDescriptor",
    "AdapterExecutionGate",
    "AdapterExecutionReceipt",
    "AdapterHealth",
    "BrowserAdapter",
    "ExecutionPolicy",
    "PlatformAdapter",
    "WindowsDesktopAdapter",
]
