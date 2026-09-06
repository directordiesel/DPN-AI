from __future__ import annotations

import asyncio

import pytest

from app.dpn_connector_ecosystem_v10 import DPNConnectorEcosystemService
from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorEvidence,
    ConnectorHealth,
    ConnectorProtocolError,
    ConnectorRequest,
    DPNConnectorRegistry,
)
from app.dpn_native_connectors_v10 import DPNNativeConnectorService, NativeConnectorConfig


class _Adapter:
    def __init__(self, kind: str):
        self.kind = kind
        self.calls = 0

    async def health(self):
        return ConnectorHealth.HEALTHY

    async def execute(self, request):
        self.calls += 1
        return ConnectorEvidence(
            connector_id=request.connector_id,
            action=request.action,
            resource=request.resource,
            provider_kind=self.kind,
            ok=True,
            health=ConnectorHealth.HEALTHY,
            result={"ok": True},
            provenance={"adapter": "test-native", "sequence": self.calls},
        )


class _EmptyService:
    def registry(self):
        return DPNConnectorRegistry()


def test_catalog_declares_all_approved_native_connector_identities_fail_closed():
    service = DPNNativeConnectorService()
    catalog = service.catalog()
    kinds = {item["kind"] for item in catalog["connectors"]}
    assert kinds == {"dpn_ecs", "dpn_watchtower", "dpn_hr", "dpn_aqua_labs", "ssh", "windows"}
    assert catalog["connector_count"] == 6
    assert all(item["configured"] is False for item in catalog["connectors"])
    assert all(item["enabled"] is False for item in catalog["connectors"])


def test_unconfigured_native_connector_cannot_execute():
    registry = DPNNativeConnectorService().registry()
    request = ConnectorRequest("native:dpn_ecs", ConnectorAction.READ, "systems")
    with pytest.raises(ConnectorProtocolError, match="not configured"):
        asyncio.run(registry.execute(request))


def test_config_without_adapter_still_fails_closed():
    service = DPNNativeConnectorService(config={"dpn_ecs": NativeConnectorConfig(configured=True, enabled=True)})
    manifest = service.registry().manifest("native:dpn_ecs")
    assert manifest is not None
    assert manifest.configured is False
    assert manifest.enabled is False


def test_configured_adapter_executes_only_declared_read_capability():
    adapter = _Adapter("dpn_ecs")
    registry = DPNNativeConnectorService(
        adapters={"dpn_ecs": adapter},
        config={"dpn_ecs": NativeConnectorConfig(configured=True, enabled=True)},
    ).registry()
    evidence = asyncio.run(registry.execute(ConnectorRequest("native:dpn_ecs", ConnectorAction.READ, "systems")))
    assert evidence.ok is True
    assert evidence.provider_kind == "dpn_ecs"
    assert adapter.calls == 1


def test_native_write_requires_explicit_approval():
    adapter = _Adapter("dpn_hr")
    registry = DPNNativeConnectorService(
        adapters={"dpn_hr": adapter},
        config={"dpn_hr": NativeConnectorConfig(configured=True, enabled=True)},
    ).registry()
    request = ConnectorRequest("native:dpn_hr", ConnectorAction.UPDATE, "employees")
    with pytest.raises(ConnectorProtocolError, match="requires explicit approval"):
        asyncio.run(registry.execute(request))
    assert adapter.calls == 0


def test_ssh_does_not_infer_arbitrary_command_execution():
    manifest = DPNNativeConnectorService().registry().manifest("native:ssh")
    assert manifest is not None
    actions = {cap.action for cap in manifest.capabilities}
    assert actions <= {ConnectorAction.READ, ConnectorAction.SEARCH}
    assert ConnectorAction.CREATE not in actions
    assert ConnectorAction.UPDATE not in actions
    assert ConnectorAction.DELETE not in actions


def test_windows_mutation_is_approval_gated():
    manifest = DPNNativeConnectorService().registry().manifest("native:windows")
    assert manifest is not None
    cap = manifest.capability_for(ConnectorAction.UPDATE, "desktop")
    assert cap is not None
    assert cap.approval_required is True


def test_unified_ecosystem_surfaces_native_connectors_as_blocked_until_configured():
    ecosystem = DPNConnectorEcosystemService(
        _EmptyService(),
        _EmptyService(),
        native_service=DPNNativeConnectorService(),
    )
    catalog = ecosystem.catalog()
    assert catalog["connector_count"] == 6
    readiness = asyncio.run(ecosystem.readiness())
    assert readiness["ready"] is False
    assert readiness["ready_count"] == 0
    assert readiness["blocked_count"] == 6
    assert readiness["blocked_reasons"]["not_configured"] == 6
    assert readiness["blocked_reasons"]["disabled"] == 6
