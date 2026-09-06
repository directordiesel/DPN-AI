from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorAdapter,
    ConnectorCapability,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorRisk,
    DPNConnectorRegistry,
)


@dataclass(frozen=True)
class NativeConnectorConfig:
    """Runtime configuration for one DPN-native connector identity.

    Native connectors are intentionally adapter-injected. Declaring a profile never
    grants host/network execution. A connector becomes executable only when a trusted
    adapter is supplied and the connector is explicitly configured + enabled.
    """

    configured: bool = False
    enabled: bool = False
    local: bool = True


def _read(resource: str) -> ConnectorCapability:
    return ConnectorCapability(ConnectorAction.READ, resource, ConnectorRisk.READ_ONLY)


def _search(resource: str) -> ConnectorCapability:
    return ConnectorCapability(ConnectorAction.SEARCH, resource, ConnectorRisk.READ_ONLY)


def _create(resource: str) -> ConnectorCapability:
    return ConnectorCapability(ConnectorAction.CREATE, resource, ConnectorRisk.WRITE, approval_required=True)


def _update(resource: str) -> ConnectorCapability:
    return ConnectorCapability(ConnectorAction.UPDATE, resource, ConnectorRisk.WRITE, approval_required=True)


def _delete(resource: str) -> ConnectorCapability:
    return ConnectorCapability(ConnectorAction.DELETE, resource, ConnectorRisk.DESTRUCTIVE, approval_required=True)


def _subscribe(resource: str) -> ConnectorCapability:
    return ConnectorCapability(ConnectorAction.SUBSCRIBE, resource, ConnectorRisk.SUBSCRIPTION, approval_required=True)


_NATIVE_CAPABILITIES: dict[str, tuple[ConnectorCapability, ...]] = {
    "dpn_ecs": (
        _read("systems"), _search("systems"), _read("servers"), _search("servers"),
        _read("alerts"), _update("servers"), _create("commands"),
    ),
    "dpn_watchtower": (
        _read("health"), _read("alerts"), _search("alerts"), _subscribe("alerts"), _update("policies"),
    ),
    "dpn_hr": (
        _read("employees"), _search("employees"), _read("payroll"), _search("payroll"),
        _create("employees"), _update("employees"), _delete("employees"),
    ),
    "dpn_aqua_labs": (
        _read("inventory"), _search("inventory"), _read("sales"), _search("sales"),
        _create("inventory"), _update("inventory"), _delete("inventory"),
    ),
    # SSH deliberately exposes inventory/session-state reads only at the protocol
    # layer. Arbitrary command execution is not inferred from the existence of SSH.
    "ssh": (
        _read("hosts"), _search("hosts"), _read("sessions"),
    ),
    # Windows host mutation is represented explicitly and remains approval-gated.
    # Concrete execution must be supplied by a trusted local adapter.
    "windows": (
        _read("system"), _read("desktop"), _search("windows"), _update("desktop"),
    ),
}

_NATIVE_NAMES = {
    "dpn_ecs": "DPN Executive Control System",
    "dpn_watchtower": "DPN WatchTower",
    "dpn_hr": "DPN Human Resources",
    "dpn_aqua_labs": "DPN Aqua Labs",
    "ssh": "SSH Hosts",
    "windows": "Windows Host",
}


class DPNNativeConnectorService:
    """Protocol registry for DPN-native and host connector identities.

    The service never guesses an implementation. Missing adapters are registered only
    as unconfigured manifests and therefore fail closed through DPNConnectorRegistry.
    """

    def __init__(
        self,
        adapters: Mapping[str, ConnectorAdapter] | None = None,
        config: Mapping[str, NativeConnectorConfig] | None = None,
    ) -> None:
        self.adapters = dict(adapters or {})
        self.config = dict(config or {})

    def registry(self) -> DPNConnectorRegistry:
        registry = DPNConnectorRegistry()
        for connector_id in sorted(_NATIVE_CAPABILITIES):
            settings = self.config.get(connector_id, NativeConnectorConfig())
            adapter = self.adapters.get(connector_id)
            configured = bool(settings.configured and adapter is not None)
            enabled = bool(settings.enabled and configured)
            manifest = ConnectorManifest(
                connector_id=f"native:{connector_id}",
                kind=connector_id,
                display_name=_NATIVE_NAMES[connector_id],
                capabilities=_NATIVE_CAPABILITIES[connector_id],
                configured=configured,
                enabled=enabled,
                local=bool(settings.local),
                version="10.0",
                metadata={
                    "adapter_injected": adapter is not None,
                    "execution_inferred": False,
                    "fail_closed_when_unconfigured": True,
                },
            )
            registry.register(manifest, adapter or _UnavailableNativeAdapter(connector_id))
        return registry

    def catalog(self) -> dict[str, object]:
        manifests = self.registry().discover()
        return {
            "ok": True,
            "connector_count": len(manifests),
            "connectors": [
                {
                    "connector_id": item.connector_id,
                    "kind": item.kind,
                    "display_name": item.display_name,
                    "configured": item.configured,
                    "enabled": item.enabled,
                    "local": item.local,
                    "capabilities": [
                        {
                            "action": cap.action.value,
                            "resource": cap.resource,
                            "risk": cap.risk.value,
                            "approval_required": cap.approval_required,
                        }
                        for cap in item.capabilities
                    ],
                }
                for item in manifests
            ],
        }


class _UnavailableNativeAdapter:
    def __init__(self, provider_kind: str) -> None:
        self.provider_kind = provider_kind

    async def health(self) -> ConnectorHealth:
        return ConnectorHealth.UNCONFIGURED

    async def execute(self, request):  # pragma: no cover - registry blocks before execution
        raise RuntimeError(f"native connector adapter is not configured: {self.provider_kind}")


__all__ = ["DPNNativeConnectorService", "NativeConnectorConfig"]
