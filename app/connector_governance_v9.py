from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExternalOperation(str, Enum):
    INSPECT = "inspect"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SYNC = "sync"
    EXECUTE = "execute"


class ExternalSystem(str, Enum):
    CONNECTOR = "connector"
    MCP = "mcp"


@dataclass(frozen=True)
class GovernanceRequest:
    system: ExternalSystem
    operation: ExternalOperation
    target_id: str
    action: str
    max_operations: int = 25
    allowed_actions: tuple[str, ...] = field(default_factory=tuple)
    discovered_actions: tuple[str, ...] = field(default_factory=tuple)
    approval_present: bool = False
    idempotency_key: str | None = None


class ConnectorGovernanceV9:
    """Deterministic policy layer above ConnectorHub and MCPBridge.

    Existing connector/MCP implementations remain responsible for network, host,
    transport, secret, and execution security. This layer only decides whether a
    requested external action is sufficiently discovered, allow-listed, bounded,
    and approved to be attempted through those hardened adapters.
    """

    MAX_OPERATIONS = 200
    WRITE_LIKE = {ExternalOperation.WRITE, ExternalOperation.DELETE, ExternalOperation.SYNC, ExternalOperation.EXECUTE}

    @staticmethod
    def _clean(value: str, label: str, limit: int = 240) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{label} is required")
        if len(text) > limit or "\x00" in text or "\r" in text or "\n" in text:
            raise ValueError(f"{label} is invalid or oversized")
        return text

    def evaluate(self, request: GovernanceRequest) -> dict[str, Any]:
        target_id = self._clean(request.target_id, "target_id")
        action = self._clean(request.action, "action")
        cap = max(1, min(int(request.max_operations), self.MAX_OPERATIONS))
        discovered = {str(item).strip() for item in request.discovered_actions if str(item).strip()}
        allowed = {str(item).strip() for item in request.allowed_actions if str(item).strip()}

        failures: list[str] = []
        write_like = request.operation in self.WRITE_LIKE
        if action not in discovered:
            failures.append("action_not_discovered")
        if action not in allowed:
            failures.append("action_not_allowlisted")
        if write_like and not request.approval_present:
            failures.append("approval_required")
        if request.operation in {ExternalOperation.WRITE, ExternalOperation.SYNC, ExternalOperation.EXECUTE} and not request.idempotency_key:
            failures.append("idempotency_key_required")
        if request.idempotency_key is not None:
            key = str(request.idempotency_key)
            if not key.strip() or len(key) > 200 or any(ch in key for ch in "\r\n\x00"):
                failures.append("invalid_idempotency_key")

        material = "|".join([request.system.value, request.operation.value, target_id, action, str(cap)])
        request_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
        return {
            "ok": not failures,
            "request_id": request_id,
            "system": request.system.value,
            "operation": request.operation.value,
            "target_id": target_id,
            "action": action,
            "max_operations": cap,
            "risk": "destructive" if request.operation == ExternalOperation.DELETE else ("external_write" if write_like else "external_read"),
            "approval_required": write_like,
            "idempotency_required": request.operation in {ExternalOperation.WRITE, ExternalOperation.SYNC, ExternalOperation.EXECUTE},
            "failures": failures,
            "policy": {
                "discovery_required": True,
                "allowlist_required": True,
                "live_adapter_revalidation_required": True,
                "plaintext_secrets_forbidden": True,
                "write_verification_required": write_like,
                "persisted_configuration_is_not_authorization": True,
            },
        }

    def build_request(
        self,
        system: str,
        operation: str,
        target_id: str,
        action: str,
        *,
        max_operations: int = 25,
        allowed_actions: list[str] | None = None,
        discovered_actions: list[str] | None = None,
        approval_present: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        try:
            normalized_system = ExternalSystem(str(system).strip().lower())
        except ValueError as exc:
            raise ValueError("system must be connector or mcp") from exc
        try:
            normalized_operation = ExternalOperation(str(operation).strip().lower())
        except ValueError as exc:
            raise ValueError("operation must be inspect, read, write, delete, sync, or execute") from exc
        return self.evaluate(
            GovernanceRequest(
                system=normalized_system,
                operation=normalized_operation,
                target_id=target_id,
                action=action,
                max_operations=max_operations,
                allowed_actions=tuple(allowed_actions or []),
                discovered_actions=tuple(discovered_actions or []),
                approval_present=bool(approval_present),
                idempotency_key=idempotency_key,
            )
        )

    @staticmethod
    def evaluate_completion(evidence: dict[str, Any] | None, *, write_expected: bool = False) -> dict[str, Any]:
        payload = dict(evidence or {})
        failures: list[str] = []
        if not payload.get("discovery_complete"):
            failures.append("discovery_missing")
        if not payload.get("allowlist_checked"):
            failures.append("allowlist_check_missing")
        if not payload.get("live_policy_revalidated"):
            failures.append("live_policy_revalidation_missing")
        if payload.get("plaintext_secret_detected"):
            failures.append("plaintext_secret_detected")
        if payload.get("partial_failure_unreconciled"):
            failures.append("partial_failure_unreconciled")
        if write_expected:
            if not payload.get("approval_evidence"):
                failures.append("approval_evidence_missing")
            if not payload.get("write_verified"):
                failures.append("write_verification_missing")
        return {
            "ok": not failures,
            "completion_allowed": not failures,
            "failures": failures,
            "evidence_required": True,
        }
