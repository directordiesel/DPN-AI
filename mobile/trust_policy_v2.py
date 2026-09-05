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

    @staticmethod
    def _strict_bool(value: bool, field: str) -> bool:
        # Do not let values such as "false", 1, or arbitrary objects become truthy
        # authorization signals when contexts are hydrated from transport payloads.
        if type(value) is not bool:
            raise TrustPolicyError(f"invalid {field} flag")
        return value

    @staticmethod
    def _session_age(value: int) -> int:
        # bool is an int subclass, so reject it explicitly. Also bound the value to
        # avoid absurd/untrusted transport values entering policy calculations.
        if type(value) is not int or value < 0 or value > 365 * 24 * 60 * 60:
            raise TrustPolicyError("invalid session age")
        return value

    @staticmethod
    def _connection_mode(value: ConnectionMode | str) -> ConnectionMode:
        if isinstance(value, ConnectionMode):
            return value
        if isinstance(value, str):
            try:
                return ConnectionMode(value.strip().lower())
            except ValueError as exc:
                raise TrustPolicyError("unsupported connection mode") from exc
        raise TrustPolicyError("unsupported connection mode")

    def evaluate(self, context: DeviceTrustContext, operation: MobileOperation | str) -> dict[str, Any]:
        device_id = self._clean_device_id(context.device_id)
        paired = self._strict_bool(context.paired, "paired")
        revoked = self._strict_bool(context.revoked, "revoked")
        remote_gateway_authenticated = self._strict_bool(
            context.remote_gateway_authenticated, "remote gateway authenticated"
        )
        approval_present = self._strict_bool(context.approval_present, "approval present")
        user_presence_confirmed = self._strict_bool(context.user_presence_confirmed, "user presence confirmed")
        session_age_seconds = self._session_age(context.session_age_seconds)
        connection_mode = self._connection_mode(context.connection_mode)

        try:
            op = operation if isinstance(operation, MobileOperation) else MobileOperation(str(operation).strip().lower())
        except ValueError as exc:
            raise TrustPolicyError("unsupported mobile operation") from exc

        failures: list[str] = []
        if not paired:
            failures.append("device_not_paired")
        if revoked:
            failures.append("device_revoked")

        remote = connection_mode == ConnectionMode.REMOTE
        max_age = self.MAX_REMOTE_SESSION_SECONDS if remote else self.MAX_LOCAL_SESSION_SECONDS
        if session_age_seconds > max_age:
            failures.append("session_expired")
        if remote and not remote_gateway_authenticated:
            failures.append("remote_gateway_not_authenticated")
        if remote and op in self.WRITE_LIKE and not user_presence_confirmed:
            failures.append("user_presence_required")
        if op in self.DESTRUCTIVE and not approval_present:
            failures.append("approval_required")

        return {
            "ok": not failures,
            "device_id": device_id,
            "operation": op.value,
            "connection_mode": connection_mode.value,
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
