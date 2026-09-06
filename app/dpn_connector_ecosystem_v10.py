from __future__ import annotations

from collections import Counter
from typing import Any

from app.dpn_connector_protocol_v10 import ConnectorHealth, ConnectorManifest, ConnectorProtocolError
from app.dpn_http_connector_adapter_v10 import HTTPConnectorProtocolService
from app.dpn_mcp_connector_adapter_v10 import MCPConnectorProtocolService
from app.dpn_sql_connector_v10 import SQLiteConnectorProtocolService


class DPNConnectorEcosystemService:
    """Unified, secret-safe inventory and health view across connector transports.

    The ecosystem layer does not execute external mutations. It aggregates only
    manifests and health from concrete protocol services, rejects duplicate connector
    identities across transports, and treats health lookup failures as unavailable.
    """

    PROTOCOL = "dpn-connector-v1"

    def __init__(
        self,
        http_service: HTTPConnectorProtocolService,
        mcp_service: MCPConnectorProtocolService,
        sql_service: SQLiteConnectorProtocolService | None = None,
    ) -> None:
        self.http_service = http_service
        self.mcp_service = mcp_service
        self.sql_service = sql_service

    def _registries(self):
        registries = [self.http_service.registry(), self.mcp_service.registry()]
        if self.sql_service is not None:
            registries.append(self.sql_service.registry())
        return tuple(registries)

    def manifests(self) -> list[ConnectorManifest]:
        manifests: list[ConnectorManifest] = []
        seen: set[str] = set()
        for registry in self._registries():
            for manifest in registry.discover():
                if manifest.connector_id in seen:
                    raise ConnectorProtocolError(
                        f"duplicate connector identity across ecosystem: {manifest.connector_id}"
                    )
                seen.add(manifest.connector_id)
                manifests.append(manifest)
        return sorted(manifests, key=lambda item: (item.kind, item.display_name, item.connector_id))

    @staticmethod
    def _capabilities(manifest: ConnectorManifest) -> list[dict[str, Any]]:
        return [
            {
                "action": capability.action.value,
                "resource": capability.resource,
                "risk": capability.risk.value,
                "approval_required": capability.approval_required,
            }
            for capability in manifest.capabilities
        ]

    def catalog(self) -> dict[str, Any]:
        manifests = self.manifests()
        kinds = Counter(item.kind for item in manifests)
        return {
            "ok": True,
            "protocol": self.PROTOCOL,
            "connector_count": len(manifests),
            "kinds": dict(sorted(kinds.items())),
            "connectors": [
                {
                    "connector_id": item.connector_id,
                    "kind": item.kind,
                    "display_name": item.display_name,
                    "configured": item.configured,
                    "enabled": item.enabled,
                    "local": item.local,
                    "version": item.version,
                    "metadata": dict(item.metadata),
                    "capabilities": self._capabilities(item),
                }
                for item in manifests
            ],
        }

    async def health(self) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        seen: set[str] = set()

        for registry in self._registries():
            for manifest in registry.discover():
                if manifest.connector_id in seen:
                    raise ConnectorProtocolError(
                        f"duplicate connector identity across ecosystem: {manifest.connector_id}"
                    )
                seen.add(manifest.connector_id)
                health = await registry.health(manifest.connector_id)
                if not isinstance(health, ConnectorHealth):
                    health = ConnectorHealth.UNAVAILABLE
                counts[health.value] += 1
                entries.append(
                    {
                        "connector_id": manifest.connector_id,
                        "kind": manifest.kind,
                        "configured": manifest.configured,
                        "enabled": manifest.enabled,
                        "health": health.value,
                    }
                )

        entries.sort(key=lambda item: (item["kind"], item["connector_id"]))
        executable = sum(
            1
            for item in entries
            if item["configured"]
            and item["enabled"]
            and item["health"] in {ConnectorHealth.HEALTHY.value, ConnectorHealth.DEGRADED.value}
        )
        return {
            "ok": True,
            "protocol": self.PROTOCOL,
            "connector_count": len(entries),
            "executable_count": executable,
            "health_counts": dict(sorted(counts.items())),
            "connectors": entries,
        }


__all__ = ["DPNConnectorEcosystemService"]
