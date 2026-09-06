from __future__ import annotations

import pytest

from app.dpn_connector_ecosystem_v10 import DPNConnectorEcosystemService
from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorCapability,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorProtocolError,
    DPNConnectorRegistry,
)


class FakeAdapter:
    def __init__(self, health: ConnectorHealth = ConnectorHealth.HEALTHY, *, explode: bool = False) -> None:
        self._health = health
        self._explode = explode

    async def health(self) -> ConnectorHealth:
        if self._explode:
            raise RuntimeError("provider secret should never escape")
        return self._health

    async def execute(self, request):
        raise AssertionError("ecosystem inventory must not execute connector actions")


class FakeService:
    def __init__(self, entries):
        self.entries = entries

    def registry(self) -> DPNConnectorRegistry:
        registry = DPNConnectorRegistry()
        for manifest, adapter in self.entries:
            registry.register(manifest, adapter)
        return registry


def manifest(connector_id: str, kind: str, *, enabled: bool = True, configured: bool = True) -> ConnectorManifest:
    return ConnectorManifest(
        connector_id=connector_id,
        kind=kind,
        display_name=connector_id,
        capabilities=(ConnectorCapability(ConnectorAction.HEALTH),),
        configured=configured,
        enabled=enabled,
        metadata={"transport": kind},
    )


def test_catalog_aggregates_transports_without_executing_or_exposing_runtime_details():
    http = FakeService([(manifest("http:a", "http"), FakeAdapter())])
    mcp = FakeService([(manifest("mcp:b", "mcp"), FakeAdapter())])
    service = DPNConnectorEcosystemService(http, mcp)

    result = service.catalog()

    assert result["ok"] is True
    assert result["protocol"] == "dpn-connector-v1"
    assert result["connector_count"] == 2
    assert result["kinds"] == {"http": 1, "mcp": 1}
    assert [item["connector_id"] for item in result["connectors"]] == ["http:a", "mcp:b"]


@pytest.mark.asyncio
async def test_health_snapshot_fails_closed_on_adapter_exception_and_counts_executable_only():
    http = FakeService([
        (manifest("http:healthy", "http"), FakeAdapter(ConnectorHealth.HEALTHY)),
        (manifest("http:broken", "http"), FakeAdapter(explode=True)),
        (manifest("http:disabled", "http", enabled=False), FakeAdapter()),
    ])
    mcp = FakeService([(manifest("mcp:degraded", "mcp"), FakeAdapter(ConnectorHealth.DEGRADED))])
    service = DPNConnectorEcosystemService(http, mcp)

    result = await service.health()

    by_id = {item["connector_id"]: item for item in result["connectors"]}
    assert by_id["http:broken"]["health"] == "unavailable"
    assert by_id["http:disabled"]["health"] == "unavailable"
    assert by_id["mcp:degraded"]["health"] == "degraded"
    assert result["executable_count"] == 2
    assert result["health_counts"] == {
        "degraded": 1,
        "healthy": 1,
        "unavailable": 2,
    }
    assert "provider secret" not in str(result)


def test_duplicate_identity_across_transports_is_rejected():
    duplicate = manifest("shared", "http")
    http = FakeService([(duplicate, FakeAdapter())])
    mcp = FakeService([(manifest("shared", "mcp"), FakeAdapter())])
    service = DPNConnectorEcosystemService(http, mcp)

    with pytest.raises(ConnectorProtocolError, match="duplicate connector identity"):
        service.catalog()
