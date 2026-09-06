from __future__ import annotations

import asyncio

import pytest

from app.dpn_connector_protocol_v10 import ConnectorAction, ConnectorProtocolError, ConnectorRequest
from app.dpn_http_connector_adapter_v10 import (
    HTTPConnectorProtocolAdapter,
    HTTPConnectorProtocolService,
    http_manifest,
)


class _FakeDB:
    def __init__(self, connector):
        self.connector = connector
        self.audit_events = []

    def get_connector(self, connector_id):
        if connector_id == self.connector["id"]:
            return dict(self.connector)
        return None

    def list_connectors(self):
        return [dict(self.connector)]

    def audit(self, event_type, message, metadata=None):
        self.audit_events.append((event_type, message, metadata or {}))


class _FakeHub:
    def __init__(self, result=None):
        self.result = result or {
            "ok": True,
            "status_code": 200,
            "url": "https://api.example.test/items?q=fish",
            "content_type": "application/json",
            "response": {"items": ["one"]},
        }
        self.calls = []

    def _validate_base_url(self, base_url):
        return (base_url.startswith("https://"), "")

    async def request(self, connector_id, **kwargs):
        self.calls.append((connector_id, kwargs))
        return dict(self.result)


def _connector(methods=None, enabled=True):
    return {
        "id": "http-1",
        "name": "Example API",
        "kind": "http",
        "enabled": enabled,
        "config": {
            "base_url": "https://api.example.test/",
            "headers": {"Authorization": "{{vault:api-token}}"},
            "allowed_methods": methods or ["GET"],
        },
    }


def test_http_manifest_derives_least_privilege_capabilities():
    manifest = http_manifest(_connector(["GET", "POST", "PATCH", "DELETE"]))
    by_action = {cap.action: cap for cap in manifest.capabilities}

    assert by_action[ConnectorAction.READ].approval_required is False
    assert by_action[ConnectorAction.SEARCH].approval_required is False
    assert by_action[ConnectorAction.CREATE].approval_required is True
    assert by_action[ConnectorAction.UPDATE].approval_required is True
    assert by_action[ConnectorAction.DELETE].approval_required is True


def test_http_manifest_does_not_invent_write_capabilities():
    manifest = http_manifest(_connector(["GET"]))
    actions = {cap.action for cap in manifest.capabilities}
    assert ConnectorAction.READ in actions
    assert ConnectorAction.SEARCH in actions
    assert ConnectorAction.CREATE not in actions
    assert ConnectorAction.UPDATE not in actions
    assert ConnectorAction.DELETE not in actions


def test_protocol_catalog_redacts_connector_secrets():
    connector = _connector(["GET", "DELETE"])
    service = HTTPConnectorProtocolService(_FakeDB(connector), _FakeHub())
    result = service.catalog()

    assert result["ok"] is True
    assert result["protocol"] == "dpn-connector-v1"
    rendered = repr(result)
    assert "api-token" not in rendered
    assert "Authorization" not in rendered
    delete = next(
        cap
        for cap in result["connectors"][0]["capabilities"]
        if cap["action"] == "delete"
    )
    assert delete["approval_required"] is True


def test_protocol_read_reuses_hardened_hub_and_audits_metadata_only():
    connector = _connector(["GET"])
    db = _FakeDB(connector)
    hub = _FakeHub()
    service = HTTPConnectorProtocolService(db, hub)

    result = asyncio.run(service.read("http-1", "/items", {"q": "fish"}))

    assert result["ok"] is True
    assert result["result"] == {"items": ["one"]}
    assert result["provenance"]["method"] == "GET"
    assert hub.calls == [
        (
            "http-1",
            {
                "method": "GET",
                "path": "/items",
                "params": {"q": "fish"},
                "json_body": None,
                "timeout_seconds": 30,
            },
        )
    ]
    assert db.audit_events[0][0] == "connector.protocol_execution"
    audit_text = repr(db.audit_events)
    assert "api-token" not in audit_text
    assert "fish" not in audit_text


def test_protocol_service_fails_closed_for_disabled_connector():
    connector = _connector(["GET"], enabled=False)
    service = HTTPConnectorProtocolService(_FakeDB(connector), _FakeHub())

    with pytest.raises(ConnectorProtocolError, match="disabled"):
        asyncio.run(service.read("http-1", "/items"))


def test_adapter_rejects_action_method_confusion_before_hub_call():
    connector = _connector(["GET", "DELETE"])
    db = _FakeDB(connector)
    hub = _FakeHub()
    adapter = HTTPConnectorProtocolAdapter(db, hub, "http-1")
    request = ConnectorRequest(
        connector_id="http-1",
        action=ConnectorAction.READ,
        payload={"method": "DELETE", "path": "/items/1"},
    )

    with pytest.raises(ConnectorProtocolError, match="not compatible"):
        asyncio.run(adapter.execute(request))
    assert hub.calls == []


def test_failed_http_response_keeps_provenance_without_false_success():
    connector = _connector(["GET"])
    db = _FakeDB(connector)
    hub = _FakeHub(
        {
            "ok": False,
            "status_code": 503,
            "url": "https://api.example.test/items",
            "content_type": "application/json",
            "response": {"error": "unavailable"},
        }
    )
    service = HTTPConnectorProtocolService(db, hub)

    result = asyncio.run(service.read("http-1", "/items"))

    assert result["ok"] is False
    assert result["health"] == "degraded"
    assert result["result"] is None
    assert result["provenance"]["status_code"] == 503
