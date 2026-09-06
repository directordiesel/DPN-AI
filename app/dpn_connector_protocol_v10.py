from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol


class ConnectorProtocolError(ValueError):
    """Raised when a connector protocol request cannot be trusted or authorized."""


class ConnectorAction(str, Enum):
    DISCOVER = "discover"
    AUTHENTICATE = "authenticate"
    CAPABILITIES = "capabilities"
    HEALTH = "health"
    READ = "read"
    SEARCH = "search"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SUBSCRIBE = "subscribe"
    REVOKE = "revoke"


class ConnectorHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNCONFIGURED = "unconfigured"


class ConnectorRisk(str, Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    SUBSCRIPTION = "subscription"
    CREDENTIAL = "credential"


READ_ACTIONS = {
    ConnectorAction.DISCOVER,
    ConnectorAction.CAPABILITIES,
    ConnectorAction.HEALTH,
    ConnectorAction.READ,
    ConnectorAction.SEARCH,
}
WRITE_ACTIONS = {ConnectorAction.CREATE, ConnectorAction.UPDATE}
DESTRUCTIVE_ACTIONS = {ConnectorAction.DELETE, ConnectorAction.REVOKE}


@dataclass(frozen=True)
class ConnectorCapability:
    action: ConnectorAction
    resource: str = "*"
    risk: ConnectorRisk = ConnectorRisk.READ_ONLY
    approval_required: bool = False

    def validate(self) -> None:
        if not self.resource.strip():
            raise ConnectorProtocolError("connector capability resource is required")
        if self.action in DESTRUCTIVE_ACTIONS and not self.approval_required:
            raise ConnectorProtocolError("destructive connector capabilities must require approval")
        if self.action in WRITE_ACTIONS and self.risk == ConnectorRisk.READ_ONLY:
            raise ConnectorProtocolError("write connector capabilities cannot be declared read-only")


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    kind: str
    display_name: str
    capabilities: tuple[ConnectorCapability, ...]
    configured: bool = True
    enabled: bool = True
    local: bool = False
    version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.connector_id.strip() or not self.kind.strip() or not self.display_name.strip():
            raise ConnectorProtocolError("connector id, kind, and display name are required")
        if not self.version.strip():
            raise ConnectorProtocolError("connector manifest version is required")
        if len({(item.action, item.resource) for item in self.capabilities}) != len(self.capabilities):
            raise ConnectorProtocolError("connector capabilities must be unique by action and resource")
        for capability in self.capabilities:
            capability.validate()

    def capability_for(self, action: ConnectorAction, resource: str) -> ConnectorCapability | None:
        exact = next((item for item in self.capabilities if item.action == action and item.resource == resource), None)
        if exact:
            return exact
        return next((item for item in self.capabilities if item.action == action and item.resource == "*"), None)


@dataclass(frozen=True)
class ConnectorRequest:
    connector_id: str
    action: ConnectorAction
    resource: str = "*"
    payload: dict[str, Any] = field(default_factory=dict)
    approval_granted: bool = False
    project_id: str = ""
    user_scope: str = ""

    def validate(self) -> None:
        if not self.connector_id.strip():
            raise ConnectorProtocolError("connector id is required")
        if not self.resource.strip():
            raise ConnectorProtocolError("connector resource is required")
        if not isinstance(self.payload, dict):
            raise ConnectorProtocolError("connector payload must be an object")


@dataclass(frozen=True)
class ConnectorAuthorization:
    allowed: bool
    reason: str
    capability: ConnectorCapability | None = None


@dataclass(frozen=True)
class ConnectorEvidence:
    connector_id: str
    action: ConnectorAction
    resource: str
    provider_kind: str
    ok: bool
    health: ConnectorHealth
    result: Any = None
    error: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)


class ConnectorAdapter(Protocol):
    async def health(self) -> ConnectorHealth: ...
    async def execute(self, request: ConnectorRequest) -> ConnectorEvidence: ...


class ConnectorPolicy:
    """Least-privilege authorization for DPN Connector Protocol actions."""

    def authorize(self, manifest: ConnectorManifest, request: ConnectorRequest) -> ConnectorAuthorization:
        manifest.validate()
        request.validate()
        if request.connector_id != manifest.connector_id:
            return ConnectorAuthorization(False, "connector request does not match manifest identity")
        if not manifest.configured:
            return ConnectorAuthorization(False, "connector is not configured")
        if not manifest.enabled:
            return ConnectorAuthorization(False, "connector is disabled")
        capability = manifest.capability_for(request.action, request.resource)
        if capability is None:
            return ConnectorAuthorization(False, "requested connector action/resource is not declared")
        if capability.approval_required and not request.approval_granted:
            return ConnectorAuthorization(False, "connector action requires explicit approval", capability)
        return ConnectorAuthorization(True, "connector action is explicitly authorized", capability)


class DPNConnectorRegistry:
    """Capability-aware registry that never infers unsupported connector behavior."""

    def __init__(self, policy: ConnectorPolicy | None = None) -> None:
        self.policy = policy or ConnectorPolicy()
        self._manifests: dict[str, ConnectorManifest] = {}
        self._adapters: dict[str, ConnectorAdapter] = {}

    def register(self, manifest: ConnectorManifest, adapter: ConnectorAdapter) -> None:
        manifest.validate()
        if manifest.connector_id in self._manifests:
            raise ConnectorProtocolError("connector id is already registered")
        self._manifests[manifest.connector_id] = manifest
        self._adapters[manifest.connector_id] = adapter

    def unregister(self, connector_id: str) -> bool:
        existed = connector_id in self._manifests
        self._manifests.pop(connector_id, None)
        self._adapters.pop(connector_id, None)
        return existed

    def discover(self) -> list[ConnectorManifest]:
        return sorted(self._manifests.values(), key=lambda item: (item.kind, item.display_name, item.connector_id))

    def manifest(self, connector_id: str) -> ConnectorManifest | None:
        return self._manifests.get(connector_id)

    async def health(self, connector_id: str) -> ConnectorHealth:
        manifest = self._manifests.get(connector_id)
        adapter = self._adapters.get(connector_id)
        if manifest is None or adapter is None or not manifest.configured:
            return ConnectorHealth.UNCONFIGURED
        if not manifest.enabled:
            return ConnectorHealth.UNAVAILABLE
        try:
            result = await adapter.health()
        except Exception:
            return ConnectorHealth.UNAVAILABLE
        if not isinstance(result, ConnectorHealth):
            return ConnectorHealth.UNAVAILABLE
        return result

    async def execute(self, request: ConnectorRequest) -> ConnectorEvidence:
        request.validate()
        manifest = self._manifests.get(request.connector_id)
        adapter = self._adapters.get(request.connector_id)
        if manifest is None or adapter is None:
            raise ConnectorProtocolError("connector is not registered")
        authorization = self.policy.authorize(manifest, request)
        if not authorization.allowed:
            raise ConnectorProtocolError(authorization.reason)
        health = await self.health(request.connector_id)
        if health in {ConnectorHealth.UNAVAILABLE, ConnectorHealth.UNCONFIGURED}:
            raise ConnectorProtocolError(f"connector is not executable while health is {health.value}")
        try:
            evidence = await adapter.execute(request)
        except Exception as exc:
            raise ConnectorProtocolError(f"connector execution failed: {type(exc).__name__}: {exc}") from exc
        if not isinstance(evidence, ConnectorEvidence):
            raise ConnectorProtocolError("connector adapter returned an invalid evidence contract")
        if evidence.connector_id != request.connector_id or evidence.action != request.action or evidence.resource != request.resource:
            raise ConnectorProtocolError("connector evidence identity does not match the authorized request")
        if evidence.provider_kind != manifest.kind:
            raise ConnectorProtocolError("connector evidence provider kind does not match manifest")
        if evidence.ok and evidence.health in {ConnectorHealth.UNAVAILABLE, ConnectorHealth.UNCONFIGURED}:
            raise ConnectorProtocolError("connector cannot report success while unavailable or unconfigured")
        if evidence.ok and not evidence.provenance:
            raise ConnectorProtocolError("successful connector evidence requires provenance")
        return evidence


__all__ = [
    "ConnectorAction",
    "ConnectorAdapter",
    "ConnectorAuthorization",
    "ConnectorCapability",
    "ConnectorEvidence",
    "ConnectorHealth",
    "ConnectorManifest",
    "ConnectorPolicy",
    "ConnectorProtocolError",
    "ConnectorRequest",
    "ConnectorRisk",
    "DPNConnectorRegistry",
]
