from __future__ import annotations

import asyncio

from app.dpn_http_connector_adapter_v10 import HTTPConnectorProtocolService


class _DB:
    def __init__(self):
        self.events = []
        self.connector = {
            "id": "retry-1",
            "name": "Retry API",
            "kind": "http",
            "enabled": True,
            "config": {
                "base_url": "https://api.example.test/",
                "headers": {},
                "allowed_methods": ["GET", "POST"],
            },
        }

    def get_connector(self, connector_id):
        return dict(self.connector) if connector_id == "retry-1" else None

    def list_connectors(self):
        return [dict(self.connector)]

    def audit(self, event_type, message, metadata=None):
        self.events.append((event_type, message, metadata or {}))


class _SequenceHub:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def _validate_base_url(self, base_url):
        return (True, "")

    async def request(self, connector_id, **kwargs):
        self.calls.append((connector_id, kwargs))
        return dict(self.results.pop(0))


def _result(ok, status):
    return {
        "ok": ok,
        "status_code": status,
        "url": "https://api.example.test/items",
        "content_type": "application/json",
        "response": {"items": ["ok"]} if ok else {"error": "temporary"},
    }


def test_read_retries_transient_failure_and_reports_attempt_count(monkeypatch):
    db = _DB()
    hub = _SequenceHub([_result(False, 503), _result(True, 200)])
    service = HTTPConnectorProtocolService(db, hub)

    async def _no_sleep(_delay):
        return None

    monkeypatch.setattr("app.dpn_http_connector_adapter_v10.asyncio.sleep", _no_sleep)
    result = asyncio.run(service.read("retry-1", "/items", retry_attempts=3))

    assert result["ok"] is True
    assert len(hub.calls) == 2
    assert result["provenance"]["attempts"] == 2
    assert db.events[-1][2]["attempts"] == 2


def test_read_does_not_retry_non_transient_http_failure(monkeypatch):
    db = _DB()
    hub = _SequenceHub([_result(False, 404), _result(True, 200)])
    service = HTTPConnectorProtocolService(db, hub)

    async def _no_sleep(_delay):
        return None

    monkeypatch.setattr("app.dpn_http_connector_adapter_v10.asyncio.sleep", _no_sleep)
    result = asyncio.run(service.read("retry-1", "/missing", retry_attempts=3))

    assert result["ok"] is False
    assert len(hub.calls) == 1
    assert result["provenance"]["attempts"] == 1


def test_approved_write_never_retries_ambiguous_failure():
    db = _DB()
    hub = _SequenceHub([_result(False, 503), _result(True, 200)])
    service = HTTPConnectorProtocolService(db, hub)

    result = asyncio.run(
        service.approved_write(
            "retry-1",
            "create",
            path="/items",
            method="POST",
            json_body={"name": "one"},
        )
    )

    assert result["ok"] is False
    assert len(hub.calls) == 1
    assert result["provenance"]["attempts"] == 1
