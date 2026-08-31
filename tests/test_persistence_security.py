from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.mcp_bridge import MCPBridge
from app.persistence_security import MAX_PERSISTED_STRING, sanitize_for_persistence


def test_persistence_redacts_nested_secret_keys_and_auth_values() -> None:
    payload = {
        "token": "plain-token",
        "nested": {
            "Authorization": "Bearer top-secret",
            "safe": "visible",
            "headers": {"x-api-key": "secret-key"},
        },
    }
    sanitized = sanitize_for_persistence(payload)
    assert sanitized["token"] == "[redacted]"
    assert sanitized["nested"]["Authorization"] == "[redacted]"
    assert sanitized["nested"]["headers"]["x-api-key"] == "[redacted]"
    assert sanitized["nested"]["safe"] == "visible"


def test_persistence_redacts_secret_references_and_bounds_payloads() -> None:
    sanitized = sanitize_for_persistence({
        "value": "{{secret:MCP_TOKEN}}",
        "large": "x" * (MAX_PERSISTED_STRING + 100),
        "binary": b"abc",
    })
    assert sanitized["value"] == "[secret reference]"
    assert "truncated" in sanitized["large"]
    assert sanitized["binary"] == "[binary omitted: 3 bytes]"


class RecordingDB:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_mcp_server(self, server_id: str):
        return {"id": server_id, "enabled": True, "allowed_tools": ["echo"], "transport": "stdio", "config": {}}

    def record_mcp_call(self, *args):
        self.calls.append(args)


@pytest.mark.asyncio
async def test_mcp_persists_redacted_arguments_and_results(monkeypatch: pytest.MonkeyPatch) -> None:
    db = RecordingDB()
    bridge = MCPBridge(db)  # type: ignore[arg-type]

    class Session:
        async def call_tool(self, tool_name, arguments):
            assert arguments["password"] == "runtime-secret"
            return SimpleNamespace(model_dump=lambda mode="json": {
                "ok": True,
                "access_token": "returned-secret",
                "message": "visible",
            })

    @asynccontextmanager
    async def fake_session(server):
        yield Session()

    monkeypatch.setattr(bridge, "_session", fake_session)
    result = await bridge.call_tool("server-1", "echo", {"password": "runtime-secret", "query": "hello"})

    assert result["ok"] is True
    assert result["result"]["access_token"] == "returned-secret"
    assert len(db.calls) == 1
    _, _, persisted_args, persisted_result, ok = db.calls[0]
    assert ok is True
    assert persisted_args["password"] == "[redacted]"
    assert persisted_args["query"] == "hello"
    assert persisted_result["access_token"] == "[redacted]"
    assert persisted_result["message"] == "visible"
