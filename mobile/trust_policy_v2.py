"""DPN AI Mobile v2 device trust and remote-action policy.

This module is intentionally transport-independent. It evaluates whether a paired
mobile device may attempt a local or remote operation before the live desktop API
and existing approval engine make the final authorization decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TrustPolicyError(ValueError):
    pass


class ConnectionMode(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class MobileOperation(str, Enum):
    READ = "read"
    CHAT = "chat"
    VOICE = "voice"
    UPLOAD = "upload"
    CREATE = "create"
    UPDATE = "update"
    EXECUTE = "execute"
    APPROVE = "approve"
    DELETE = "delete"


@dataclass(frozen=True)
class DeviceTrustContext:
    device_id: str
    paired: bool
    revoked: bool = False
    connection_mode: ConnectionMode = ConnectionMode.LOCAL
    session_age_seconds: int = 0
    remote_gateway_authenticated: bool = False
    approval_present: bool = False
    user_presence_confirmed: bool = False


class MobileTrustPolicyV2:
    """Fail-closed policy for mobile v2 sessions and remote operations."""

    MAX_LOCAL_SESSION_SECONDS = 24 * 60 * 60
    MAX_REMOTE_SESSION_SECONDS = 8 * 60 * 60
    WRITE_LIKE = {
        MobileOperation.CREATE,
        MobileOperation.UPDATE,
        MobileOperation.EXECUTE,
        MobileOperation.APPROVE,
        MobileOperation.DELETE,
    }
    DESTRUCTIVE = {MobileOperation.EXECUTE, MobileOperation.APPROVE, MobileOperation.DELETE}

    @staticmethod
    def _clean_device_id(value: str) -> str:
        text = str(value or "").strip()
        if not text or len(text) > 128 or any(ch in text for ch in "\r\n\x00"):
            raise TrustPolicyError("invalid device identifier")
        return text

    def evaluate(self, context: DeviceTrustContext, operation: MobileOperation | str) -> dict[str, Any]:
        device_id = self._clean_device_id(context.device_id)
        try:
            op = operation if isinstance(operation, MobileOperation) else MobileOperation(str(operation).strip().lower())
        except ValueError as exc:
            raise TrustPolicyError("unsupported mobile operation") from exc

        failures: list[str] = []
        if not context.paired:
            failures.append("device_not_paired")
        if context.revoked:
            failures.append("device_revoked")
        if context.session_age_seconds < 0:
            failures.append("invalid_session_age")

        remote = context.connection_mode == ConnectionMode.REMOTE
        max_age = self.MAX_REMOTE_SESSION_SECONDS if remote else self.MAX_LOCAL_SESSION_SECONDS
        if context.session_age_seconds > max_age:
            failures.append("session_expired")
        if remote and not context.remote_gateway_authenticated:
            failures.append("remote_gateway_not_authenticated")
        if remote and op in self.WRITE_LIKE and not context.user_presence_confirmed:
            failures.append("user_presence_required")
        if op in self.DESTRUCTIVE and not context.approval_present:
            failures.append("approval_required")

        return {
            "ok": not failures,
            "device_id": device_id,
            "operation": op.value,
            "connection_mode": context.connection_mode.value,
            "risk": "destructive" if op in self.DESTRUCTIVE else ("write" if op in self.WRITE_LIKE else "read"),
            "approval_required": op in self.DESTRUCTIVE,
            "user_presence_required": remote and op in self.WRITE_LIKE,
            "max_session_age_seconds": max_age,
            "failures": failures,
            "policy": {
                "device_pairing_required": True,
                "revocation_checked": True,
                "remote_gateway_auth_required": remote,
                "desktop_authorization_still_required": True,
                "mobile_policy_is_not_final_authorization": True,
            },
        }


__all__ = [
    "ConnectionMode",
    "DeviceTrustContext",
    "MobileOperation",
    "MobileTrustPolicyV2",
    "TrustPolicyError",
]
