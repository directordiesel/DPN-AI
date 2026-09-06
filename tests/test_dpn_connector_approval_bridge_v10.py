from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.dpn_connector_protocol_v10 import ConnectorProtocolError
from app.dpn_http_connector_adapter_v10 import HTTPConnectorProtocolService
from app.tool_permission_runtime import ToolPermissionRuntime
from plugins.dpn_connector_protocol_v10 import register


class _FakeDB:
    def __init__(self, methods=None):
        self.connector = {
            "id": "http-write-1",
            "name": "Write API",
            "kind": "http",
            "enabled": True,
            "config": {
                "base_url": "https://api.example.test/",
                "headers": {"Authorization": "{{vault:token}}"},
                "allowed_methods": methods or ["GET", "POST", "PATCH", "DELETE"],
            },
        }
        self.events = []

    def get_connector(self, connector_id):
        return dict(self.connector) if connector_id == self.connector["id"] else None

    def list_connectors(self):
        return [dict(self.connector)]

    def audit(self, event_type, message, metadata=None):
        self.events.append((event_type, message, metadata or {}))


class _FakeHub:
    def __init__(self):
        self.calls = []

    def _validate_base_url(self, base_url):
        return (base_url.startswith("https://"), "")

    async def request(self, connector_id, **kwargs):
        self.calls.append((connector_id, kwargs))
        return {
            "ok": True,
            "status_code": 201,
            "url": "https://api.example.test/items/1",
            "content_type": "application/json",
            "response": {"id": "1"},
        }


def _permissions(mode="autonomous", allow_connectors=True, allow_mcp=True):
    return {
        "allow_connectors": allow_connectors,
        "allow_mcp": allow_mcp,
        "approval_mode": mode,
        "use_v9_permissions": False,
    }


def test_connector_write_is_human_approval_gated_even_in_autonomous_mode():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="dpn_connector_write",
        declared_risk="destructive",
        gate="connectors",
        permissions=_permissions("autonomous"),
        arguments={"connector_id": "http-write-1", "action": "delete"},
    )

    assert result.allowed is False
    assert result.approval_required is True
    assert result.decision.source == "connector_write_boundary"


def test_mcp_connector_call_is_human_approval_gated_even_in_autonomous_mode():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="dpn_connector_mcp_call",
        declared_risk="destructive",
        gate="mcp",
        permissions=_permissions("autonomous"),
        arguments={"connector_id": "mcp:srv-1", "tool_name": "mutate"},
    )

    assert result.allowed is False
    assert result.approval_required is True
    assert result.decision.source == "connector_write_boundary"


def test_connector_write_cannot_bypass_disabled_connector_gate():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="dpn_connector_write",
        declared_risk="destructive",
        gate="connectors",
        permissions=_permissions("autonomous", allow_connectors=False),
        arguments={"connector_id": "http-write-1", "action": "delete"},
    )

    assert result.allowed is False
    assert result.approval_required is False
    assert "disabled" in result.reason


def test_mcp_connector_call_cannot_bypass_disabled_mcp_gate():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="dpn_connector_mcp_call",
        declared_risk="destructive",
        gate="mcp",
        permissions=_permissions("autonomous", allow_mcp=False),
        arguments={"connector_id": "mcp:srv-1", "tool_name": "mutate"},
    )

    assert result.allowed is False
    assert result.approval_required is False
    assert "disabled" in result.reason


def test_approved_write_executes_only_declared_write_action_and_method():
    db = _FakeDB()
    hub = _FakeHub()
    service = HTTPConnectorProtocolService(db, hub)

    result = asyncio.run(
        service.approved_write(
            "http-write-1",
            "create",
            path="/items",
            method="POST",
            json_body={"name": "filter"},
        )
    )

    assert result["ok"] is True
    assert result["action"] == "create"
    assert result["provenance"]["method"] == "POST"
    assert hub.calls[0][1]["method"] == "POST"
    assert "filter" not in repr(db.events)


def test_approved_write_rejects_read_actions():
    service = HTTPConnectorProtocolService(_FakeDB(), _FakeHub())

    with pytest.raises(ConnectorProtocolError, match="create, update, or delete"):
        asyncio.run(service.approved_write("http-write-1", "read", path="/items"))


def test_approved_write_rejects_action_method_confusion_before_network():
    db = _FakeDB()
    hub = _FakeHub()
    service = HTTPConnectorProtocolService(db, hub)

    with pytest.raises(ConnectorProtocolError, match="not compatible"):
        asyncio.run(service.approved_write("http-write-1", "delete", path="/items/1", method="POST"))
    assert hub.calls == []


def test_protocol_plugin_registers_governed_http_and_mcp_tools():
    registered = {}

    class _Registry:
        db = _FakeDB()
        connectors = _FakeHub()
        mcp = SimpleNamespace()

        def register(self, *, name, description, parameters, function, gate=None, risk="read"):
            registered[name] = SimpleNamespace(
                description=description,
                parameters=parameters,
                function=function,
                gate=gate,
                risk=risk,
            )

    register(_Registry())

    assert set(registered) == {
        "dpn_connector_catalog",
        "dpn_connector_read",
        "dpn_connector_write",
        "dpn_connector_mcp_catalog",
        "dpn_connector_mcp_discover",
        "dpn_connector_mcp_call",
    }
    assert registered["dpn_connector_write"].gate == "connectors"
    assert registered["dpn_connector_write"].risk == "destructive"
    assert registered["dpn_connector_write"].parameters["properties"]["action"]["enum"] == [
        "create",
        "update",
        "delete",
    ]
    assert registered["dpn_connector_mcp_call"].gate == "mcp"
    assert registered["dpn_connector_mcp_call"].risk == "destructive"
    assert "approval" in registered["dpn_connector_mcp_call"].description.lower()
