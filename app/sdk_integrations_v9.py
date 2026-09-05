from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class SDKContractError(ValueError):
    pass


class IntegrationOperation(str, Enum):
    DISCOVER = "discover"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"


@dataclass(frozen=True)
class CapabilityDescriptor:
    name: str
    version: str
    operations: frozenset[IntegrationOperation]
    requires_approval: bool = False

    def validate(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise SDKContractError("capability name is required and must be <= 120 characters")
        if not self.version.strip() or len(self.version) > 40:
            raise SDKContractError("capability version is required and must be <= 40 characters")
        if not self.operations:
            raise SDKContractError("capability must expose at least one operation")


@dataclass(frozen=True)
class SDKRequest:
    capability: str
    operation: IntegrationOperation
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    approval_granted: bool = False


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    sequence: int
    payload: dict[str, Any]
    signature: str = ""


class SDKIntegrationRuntime:
    """Transport-independent SDK/integration validation for DPN AI v9.

    This does not replace ConnectorHub, MCPBridge, or HTTP transport. It gives
    external callers a deterministic contract that those systems can enforce.
    """

    WRITE_LIKE = {IntegrationOperation.WRITE, IntegrationOperation.DELETE, IntegrationOperation.EXECUTE}

    @staticmethod
    def _canonical(data: dict[str, Any]) -> bytes:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")

    @staticmethod
    def discover(capabilities: Iterable[CapabilityDescriptor]) -> tuple[CapabilityDescriptor, ...]:
        items = list(capabilities)
        names: set[str] = set()
        for item in items:
            item.validate()
            key = item.name.strip().lower()
            if key in names:
                raise SDKContractError("duplicate capability name")
            names.add(key)
        return tuple(sorted(items, key=lambda item: item.name.lower()))

    @classmethod
    def validate_request(cls, request: SDKRequest, capabilities: Iterable[CapabilityDescriptor]) -> CapabilityDescriptor:
        if not request.capability.strip():
            raise SDKContractError("capability is required")
        discovered = cls.discover(capabilities)
        capability = next((item for item in discovered if item.name == request.capability), None)
        if capability is None:
            raise SDKContractError("requested capability was not discovered")
        if request.operation not in capability.operations:
            raise SDKContractError("operation is not supported by capability")
        if request.operation in cls.WRITE_LIKE:
            key = request.idempotency_key.strip()
            if not key or len(key) > 200:
                raise SDKContractError("write-like operations require a bounded idempotency key")
            if capability.requires_approval and not request.approval_granted:
                raise SDKContractError("operation requires explicit approval")
        return capability

    @classmethod
    def build_event(cls, *, event_type: str, sequence: int, payload: dict[str, Any], signing_key: bytes | None = None) -> EventEnvelope:
        if not event_type.strip() or len(event_type) > 160:
            raise SDKContractError("event type is required and must be <= 160 characters")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise SDKContractError("event sequence must be a non-negative integer")
        base = {"event_type": event_type.strip(), "sequence": sequence, "payload": payload}
        event_id = hashlib.sha256(cls._canonical(base)).hexdigest()[:32]
        signature = hmac.new(signing_key, cls._canonical({**base, "event_id": event_id}), hashlib.sha256).hexdigest() if signing_key else ""
        return EventEnvelope(event_id=event_id, event_type=base["event_type"], sequence=sequence, payload=dict(payload), signature=signature)

    @classmethod
    def verify_event(cls, event: EventEnvelope, *, signing_key: bytes) -> bool:
        if not signing_key or len(event.signature) != 64:
            return False
        rebuilt = cls.build_event(event_type=event.event_type, sequence=event.sequence, payload=event.payload, signing_key=signing_key)
        return hmac.compare_digest(rebuilt.event_id, event.event_id) and hmac.compare_digest(rebuilt.signature, event.signature)

    @classmethod
    def verify_webhook(cls, *, raw_body: bytes, signature: str, signing_key: bytes) -> bool:
        if not signing_key or not isinstance(raw_body, (bytes, bytearray)):
            return False
        supplied = str(signature or "").strip().lower()
        if supplied.startswith("sha256="):
            supplied = supplied[7:]
        if len(supplied) != 64 or any(ch not in "0123456789abcdef" for ch in supplied):
            return False
        expected = hmac.new(signing_key, bytes(raw_body), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied)


__all__ = ["CapabilityDescriptor", "EventEnvelope", "IntegrationOperation", "SDKContractError", "SDKIntegrationRuntime", "SDKRequest"]
