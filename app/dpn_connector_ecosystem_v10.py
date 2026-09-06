from __future__ import annotations

from collections import Counter
from typing import Any

from app.dpn_connector_protocol_v10 import ConnectorAction, ConnectorHealth, ConnectorManifest, ConnectorProtocolError
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

    async def readiness(self) -> dict[str, Any]:
        """Return deterministic fail-closed operational readiness evidence.

        This report is intentionally derived from manifests plus connector health only.
        It does not execute connector actions, decrypt credentials, or include provider
        response bodies. A connector is ready only when it is configured, enabled, and
        healthy/degraded according to its transport adapter.
        """
        manifests = self.manifests()
        health_snapshot = await self.health()
        health_by_id = {
            item["connector_id"]: item["health"] for item in health_snapshot["connectors"]
        }

        entries: list[dict[str, Any]] = []
        ready_count = 0
        approval_capability_count = 0
        blocked_reasons: Counter[str] = Counter()

        for manifest in manifests:
            health = health_by_id.get(manifest.connector_id, ConnectorHealth.UNAVAILABLE.value)
            reasons: list[str] = []
            if not manifest.configured:
                reasons.append("not_configured")
            if not manifest.enabled:
                reasons.append("disabled")
            # A disabled connector is intentionally administratively blocked, not
            # independently unhealthy. Only enabled connectors receive transport-health
            # failure evidence; this keeps readiness reasons non-redundant while still
            # failing closed for enabled/unconfigured or otherwise unavailable entries.
            if manifest.enabled and health not in {
                ConnectorHealth.HEALTHY.value,
                ConnectorHealth.DEGRADED.value,
            }:
                reasons.append("unhealthy")

            approval_actions = sorted(
                capability.action.value
                for capability in manifest.capabilities
                if capability.approval_required
            )
            approval_capability_count += len(approval_actions)
            ready = not reasons
            ready_count += int(ready)
            for reason in reasons:
                blocked_reasons[reason] += 1

            entries.append(
                {
                    "connector_id": manifest.connector_id,
                    "kind": manifest.kind,
                    "ready": ready,
                    "health": health,
                    "approval_required_actions": approval_actions,
                    "blocked_reasons": reasons,
                }
            )

        entries.sort(key=lambda item: (item["kind"], item["connector_id"]))
        connector_count = len(entries)
        return {
            "ok": True,
            "protocol": self.PROTOCOL,
            "ready": connector_count > 0 and ready_count == connector_count,
            "connector_count": connector_count,
            "ready_count": ready_count,
            "blocked_count": connector_count - ready_count,
            "approval_required_capability_count": approval_capability_count,
            "blocked_reasons": dict(sorted(blocked_reasons.items())),
            "connectors": entries,
        }

    async def release_evidence(self) -> dict[str, Any]:
        """Produce deterministic connector contract and operational release evidence.

        The release gate is intentionally stricter than a health snapshot. Any manifest
        that advertises create/update/delete without explicit approval is a contract
        violation and makes the connector batch ineligible for release. This method does
        not execute connector actions, decrypt credentials, or include provider payloads.
        """
        manifests = self.manifests()
        readiness = await self.readiness()
        mutation_actions = {
            ConnectorAction.CREATE,
            ConnectorAction.UPDATE,
            ConnectorAction.DELETE,
        }
        violations: list[dict[str, str]] = []
        approval_protected_mutations = 0

        for manifest in manifests:
            for capability in manifest.capabilities:
                if capability.action not in mutation_actions:
                    continue
                if capability.approval_required:
                    approval_protected_mutations += 1
                    continue
                violations.append(
                    {
                        "connector_id": manifest.connector_id,
                        "action": capability.action.value,
                        "reason": "mutation_without_explicit_approval",
                    }
                )

        violations.sort(key=lambda item: (item["connector_id"], item["action"]))
        kinds = dict(sorted(Counter(item.kind for item in manifests).items()))
        contract_ready = bool(manifests) and not violations
        operational_ready = bool(readiness["ready"])
        return {
            "ok": True,
            "protocol": self.PROTOCOL,
            "release_ready": contract_ready and operational_ready,
            "contract_ready": contract_ready,
            "operational_ready": operational_ready,
            "connector_count": len(manifests),
            "transport_kinds": kinds,
            "approval_protected_mutation_count": approval_protected_mutations,
            "contract_violation_count": len(violations),
            "contract_violations": violations,
            "operational": {
                "ready_count": readiness["ready_count"],
                "blocked_count": readiness["blocked_count"],
                "blocked_reasons": readiness["blocked_reasons"],
            },
        }


__all__ = ["DPNConnectorEcosystemService"]
