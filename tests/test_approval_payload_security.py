from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.db import Database
from app.vault import SecretVault
from plugins.approval_payload_security import register


class DummyTool:
    risk = "external"


class DummyRegistry:
    def __init__(self, tmp_path: Path):
        self.db = Database(tmp_path / "data.sqlite3")
        self.vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
        self.tools = {"send": DummyTool()}
        self.invocations = []

    def _gate_error(self, registered, permissions):
        return None

    async def _invoke(self, name, arguments):
        self.invocations.append((name, arguments))
        return {"ok": True, "echo": arguments}


def test_approval_sqlite_contains_only_redacted_preview(tmp_path):
    registry = DummyRegistry(tmp_path)
    register(registry)
    secret = "TOP-SECRET-APPROVAL-VALUE"
    result = asyncio.run(registry.execute(
        "send",
        {"password": secret, "nested": {"authorization": "Bearer abc123"}, "message": "safe"},
        {"approval_mode": "standard"},
    ))
    assert result["approval_required"] is True
    approval_id = result["approval_id"]

    raw_db = (tmp_path / "data.sqlite3").read_bytes()
    assert secret.encode() not in raw_db
    approval = registry.db.get_approval(approval_id)
    assert approval["arguments"]["password"] == "[redacted]"
    assert approval["arguments"]["nested"]["authorization"] == "[redacted]"
    assert approval["arguments"]["message"] == "safe"
    assert registry.vault.get_value(f"approval_payload.{approval_id}")


def test_approved_execution_uses_exact_payload_then_deletes_it(tmp_path):
    registry = DummyRegistry(tmp_path)
    register(registry)
    arguments = {"password": "real-secret", "message": "deliver exactly"}
    requested = asyncio.run(registry.execute("send", arguments, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]

    registry.db.resolve_approval(approval_id, "approved")
    executed = asyncio.run(registry.execute_approval(approval_id))
    assert executed["ok"] is True
    assert registry.invocations == [("send", arguments)]
    assert registry.db.get_approval(approval_id)["status"] == "executed"
    try:
        registry.vault.get_value(f"approval_payload.{approval_id}")
        assert False, "terminal approval payload must be deleted"
    except KeyError:
        pass


def test_denied_approval_deletes_encrypted_payload(tmp_path):
    registry = DummyRegistry(tmp_path)
    register(registry)
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "denied")
    try:
        registry.vault.get_value(f"approval_payload.{approval_id}")
        assert False, "denied approval payload must be deleted"
    except KeyError:
        pass


def test_missing_payload_fails_closed_without_execution(tmp_path):
    registry = DummyRegistry(tmp_path)
    register(registry)
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")
    registry.vault.delete(f"approval_payload.{approval_id}")

    result = asyncio.run(registry.execute_approval(approval_id))
    assert result["ok"] is False
    assert registry.invocations == []
    assert registry.db.get_approval(approval_id)["status"] == "failed"
