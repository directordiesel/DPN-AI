from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.approval_security import ApprovalSecurity
from app.db import Database
from app.vault import SecretVault


class DummyTool:
    risk = "external"


class DummyRegistry:
    def __init__(self, tmp_path: Path):
        self.db = Database(tmp_path / "data.sqlite3")
        self.vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
        self.tools = {"send": DummyTool()}
        self.invocations = []
        self.approval_security = ApprovalSecurity(self)

    def _gate_error(self, registered, permissions):
        return None

    async def _invoke(self, name, arguments):
        self.invocations.append((name, arguments))
        return {"ok": True, "echo": arguments}

    async def execute(self, name, arguments, permissions):
        return await self.approval_security.execute(name, arguments, permissions)

    async def execute_approval(self, approval_id):
        return await self.approval_security.execute_approval(approval_id)


def test_approval_sqlite_contains_only_redacted_preview(tmp_path):
    registry = DummyRegistry(tmp_path)
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
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")
    registry.vault.delete(f"approval_payload.{approval_id}")

    result = asyncio.run(registry.execute_approval(approval_id))
    assert result["ok"] is False
    assert registry.invocations == []
    assert registry.db.get_approval(approval_id)["status"] == "failed"


def test_legacy_plaintext_approval_is_scrubbed_on_registration(tmp_path):
    db = Database(tmp_path / "data.sqlite3")
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    secret = "LEGACY-PLAINTEXT-TOKEN"
    approval = db.create_approval("send", {"token": secret, "message": "keep"}, "external", "legacy")
    assert secret.encode() in (tmp_path / "data.sqlite3").read_bytes()

    class LegacyRegistry:
        def __init__(self):
            self.db = db
            self.vault = vault
            self.tools = {"send": DummyTool()}

        def _gate_error(self, registered, permissions):
            return None

        async def _invoke(self, name, arguments):
            return {"ok": True}

    ApprovalSecurity(LegacyRegistry())

    cleaned = db.get_approval(approval["id"])
    assert cleaned["arguments"]["token"] == "[redacted]"
    assert cleaned["arguments"]["message"] == "keep"
    assert secret.encode() not in (tmp_path / "data.sqlite3").read_bytes()


def test_expired_approval_is_denied_and_payload_destroyed(tmp_path):
    registry = DummyRegistry(tmp_path)
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with registry.db.connect() as connection:
        connection.execute("UPDATE approval_requests SET created_at=? WHERE id=?", (old, approval_id))
        connection.execute("UPDATE approval_requests SET status='approved' WHERE id=?", (approval_id,))

    result = asyncio.run(registry.execute_approval(approval_id))
    assert result["ok"] is False
    assert "expired" in result["error"].lower()
    assert registry.invocations == []
    assert registry.db.get_approval(approval_id)["status"] == "denied"
    try:
        registry.vault.get_value(f"approval_payload.{approval_id}")
        assert False, "expired approval payload must be deleted"
    except KeyError:
        pass


def test_tool_exception_fails_approval_and_destroys_payload(tmp_path):
    registry = DummyRegistry(tmp_path)

    async def exploding(name, arguments):
        raise RuntimeError("Bearer must-not-persist")

    registry._invoke = exploding
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")

    result = asyncio.run(registry.execute_approval(approval_id))
    assert result["ok"] is False
    approval = registry.db.get_approval(approval_id)
    assert approval["status"] == "failed"
    assert "must-not-persist" not in str(approval.get("result"))
    try:
        registry.vault.get_value(f"approval_payload.{approval_id}")
        assert False, "failed approval payload must be deleted"
    except KeyError:
        pass


def test_interrupted_executing_approval_is_failed_on_startup(tmp_path):
    registry = DummyRegistry(tmp_path)
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    with registry.db.connect() as connection:
        connection.execute("UPDATE approval_requests SET status='executing' WHERE id=?", (approval_id,))
    assert registry.vault.get_value(f"approval_payload.{approval_id}")

    second = DummyRegistry(tmp_path)
    approval = second.db.get_approval(approval_id)
    assert approval["status"] == "failed"
    assert "replay blocked" in str(approval.get("result", {})).lower()
    try:
        second.vault.get_value(f"approval_payload.{approval_id}")
        assert False, "interrupted approval payload must be deleted"
    except KeyError:
        pass
