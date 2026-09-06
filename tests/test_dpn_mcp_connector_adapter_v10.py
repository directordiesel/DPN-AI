from __future__ import annotations

import pytest

from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorProtocolError,
    ConnectorRequest,
    ConnectorRisk,
    DPNConnectorRegistry,
)
from app.dpn_mcp_connector_adapter_v10 import MCPConnectorProtocolAdapter, MCPConnectorProtocolService


class FakeDB:
    def __init__(self) -> None:
        self.server = {
            "id": "srv-1",
            "name": "Local MCP",
            "transport": "stdio",
            "enabled": True,
            "allowed_tools": ["lookup", "mutate"],
            "config": {"env": {"TOKEN": "[configured]"}},
        }

    def get_mcp_server(self, server_id: str):
        return dict(self.server) if server_id == self.server["id"] else None


class FakeBridge:
    def __init__(self) -> None:
        self.db = FakeDB()
        self.calls = []
        self.discovery_calls = 0

    def status(self):
        return {"ok": True, "available": True}

    def list_servers(self):
        return {"ok": True, "servers": [dict(self.db.server)]}

    async def discover(self, server_id: str):
        self.discovery_calls += 1
        return {"ok": True, "server_id": server_id, "tool_count": 2, "tools": [{"name": "lookup"}, {"name": "mutate"}]}

    async def call_tool(self, server_id: str, tool_name: str, arguments):
        self.calls.append((server_id, tool_name, arguments))
        return {"ok": True, "server_id": server_id, "tool": tool_name, "result": {"accepted": True}}


def test_manifest_only_exposes_allowlisted_tools_as_approval_required_write_risk():
    adapter = MCPConnectorProtocolAdapter(FakeBridge(), "srv-1")
    manifest = adapter.manifest()

    assert manifest.connector_id == "mcp:srv-1"
    assert manifest.kind == "mcp"
    assert manifest.local is True
    assert manifest.metadata == {"transport": "stdio", "approved_tool_count": 2}
    tool_caps = [item for item in manifest.capabilities if item.resource.startswith("tool:")]
    assert {item.resource for item in tool_caps} == {"tool:lookup", "tool:mutate"}
    assert all(item.action == ConnectorAction.UPDATE for item in tool_caps)
    assert all(item.risk == ConnectorRisk.WRITE for item in tool_caps)
    assert all(item.approval_required for item in tool_caps)


@pytest.mark.asyncio
async def test_registry_blocks_mcp_tool_call_without_trusted_approval():
    bridge = FakeBridge()
    adapter = MCPConnectorProtocolAdapter(bridge, "srv-1")
    registry = DPNConnectorRegistry()
    registry.register(adapter.manifest(), adapter)

    with pytest.raises(ConnectorProtocolError, match="requires explicit approval"):
        await registry.execute(
            ConnectorRequest(
                connector_id="mcp:srv-1",
                action=ConnectorAction.UPDATE,
                resource="tool:mutate",
                payload={"arguments": {"value": 1}},
            )
        )
    assert bridge.calls == []


@pytest.mark.asyncio
async def test_approved_mcp_tool_call_rechecks_current_allowlist_before_execution():
    bridge = FakeBridge()
    adapter = MCPConnectorProtocolAdapter(bridge, "srv-1")
    request = ConnectorRequest(
        connector_id="mcp:srv-1",
        action=ConnectorAction.UPDATE,
        resource="tool:mutate",
        payload={"arguments": {"value": 1}},
        approval_granted=True,
    )

    bridge.db.server["allowed_tools"] = ["lookup"]
    with pytest.raises(ConnectorProtocolError, match="current server allowlist"):
        await adapter.execute(request)
    assert bridge.calls == []


@pytest.mark.asyncio
async def test_approved_mcp_tool_call_returns_bounded_provenance_without_arguments():
    bridge = FakeBridge()
    adapter = MCPConnectorProtocolAdapter(bridge, "srv-1")
    registry = DPNConnectorRegistry()
    registry.register(adapter.manifest(), adapter)

    evidence = await registry.execute(
        ConnectorRequest(
            connector_id="mcp:srv-1",
            action=ConnectorAction.UPDATE,
            resource="tool:lookup",
            payload={"arguments": {"secret_input": "do-not-copy-to-provenance"}},
            approval_granted=True,
        )
    )

    assert evidence.ok is True
    assert evidence.provenance == {
        "provider": "mcp",
        "server_id": "srv-1",
        "operation": "call_tool",
        "tool": "lookup",
    }
    assert "secret_input" not in str(evidence.provenance)
    assert bridge.calls == [("srv-1", "lookup", {"secret_input": "do-not-copy-to-provenance"})]


@pytest.mark.asyncio
async def test_discovery_is_read_only_and_does_not_require_tool_approval():
    bridge = FakeBridge()
    adapter = MCPConnectorProtocolAdapter(bridge, "srv-1")
    registry = DPNConnectorRegistry()
    registry.register(adapter.manifest(), adapter)

    evidence = await registry.execute(
        ConnectorRequest(connector_id="mcp:srv-1", action=ConnectorAction.DISCOVER, resource="tools")
    )

    assert evidence.ok is True
    assert evidence.result["tool_count"] == 2
    assert bridge.discovery_calls == 1
    assert bridge.calls == []


def test_service_discovers_configured_servers_without_exposing_config_secrets_in_manifest():
    service = MCPConnectorProtocolService(FakeBridge())
    manifests = service.manifests()

    assert len(manifests) == 1
    assert manifests[0].connector_id == "mcp:srv-1"
    assert "TOKEN" not in str(manifests[0].metadata)
    assert "configured" not in str(manifests[0].metadata)


@pytest.mark.asyncio
async def test_adapter_rejects_unknown_action_resource_even_with_approval():
    bridge = FakeBridge()
    adapter = MCPConnectorProtocolAdapter(bridge, "srv-1")

    with pytest.raises(ConnectorProtocolError, match="not executable"):
        await adapter.execute(
            ConnectorRequest(
                connector_id="mcp:srv-1",
                action=ConnectorAction.DELETE,
                resource="tool:lookup",
                approval_granted=True,
            )
        )
    assert bridge.calls == []
