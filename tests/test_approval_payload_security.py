from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db import Database
from app.vault import SecretVault
from plugins.approval_payload_security import register


class DummyTool:
    risk = "external"


class DummyRegistry:
    def __init__(self, tmp_path: Path, *, fail: bool = False, cancel: bool = False):
        self.db = Database(tmp_path / "data.sqlite3")
        self.vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
        self.tools = {"send": DummyTool()}
        self.invocations = []
        self.fail = fail
        self.cancel = cancel

    def _gate_error(self, registered, permissions):
        return None

    async def _invoke(self, name, arguments):
        self.invocations.append((name, arguments))
        if self.cancel:
            raise asyncio.CancelledError()
        if self.fail:
            raise RuntimeError("Bearer execution-secret")
        return {"ok": True, "echo": arguments}


def _assert_payload_deleted(registry: DummyRegistry, approval_id: str) -> None:
    with pytest.raises(KeyError):
        registry.vault.get_value(f"approval_payload.{approval_id}")


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
    _assert_payload_deleted(registry, approval_id)


def test_denied_approval_deletes_encrypted_payload(tmp_path):
    registry = DummyRegistry(tmp_path)
    register(registry)
    requested = asyncio.run(registry.execute("send", {"token": "abc"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "denied")
    _assert_payload_deleted(registry, approval_id)


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


def test_legacy_plaintext_approval_is_scrubbed_on_registration(tmp_path):
    registry = DummyRegistry(tmp_path)
    secret = "LEGACY-PLAINTEXT-TOKEN"
    approval = registry.db.create_approval("send", {"token": secret, "message": "keep"}, "external", "legacy")
    assert secret.encode() in (tmp_path / "data.sqlite3").read_bytes()

    register(registry)

    cleaned = registry.db.get_approval(approval["id"])
    assert cleaned["arguments"]["token"] == "[redacted]"
    assert cleaned["arguments"]["message"] == "keep"
    assert secret.encode() not in (tmp_path / "data.sqlite3").read_bytes()


def test_expired_approval_is_denied_and_payload_destroyed(tmp_path):
    registry = DummyRegistry(tmp_path)
    register(registry)
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
    _assert_payload_deleted(registry, approval_id)


def test_tool_exception_marks_approval_failed_and_destroys_payload(tmp_path):
    registry = DummyRegistry(tmp_path, fail=True)
    register(registry)
    requested = asyncio.run(registry.execute(
        "send",
        {"password": "execution-secret"},
        {"approval_mode": "standard"},
    ))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")

    result = asyncio.run(registry.execute_approval(approval_id))

    assert result == {"ok": False, "error": "Approved tool execution failed"}
    approval = registry.db.get_approval(approval_id)
    assert approval["status"] == "failed"
    assert "execution-secret" not in str(approval.get("result"))
    _assert_payload_deleted(registry, approval_id)


def test_cancelled_execution_blocks_replay_and_destroys_payload(tmp_path):
    registry = DummyRegistry(tmp_path, cancel=True)
    register(registry)
    requested = asyncio.run(registry.execute("send", {"message": "once"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(registry.execute_approval(approval_id))

    assert registry.db.get_approval(approval_id)["status"] == "failed"
    _assert_payload_deleted(registry, approval_id)


def test_interrupted_executing_approval_is_failed_on_restart_without_replay(tmp_path):
    first = DummyRegistry(tmp_path)
    register(first)
    requested = asyncio.run(first.execute("send", {"password": "restart-secret"}, {"approval_mode": "standard"}))
    approval_id = requested["approval_id"]
    first.db.resolve_approval(approval_id, "approved")
    with first.db.connect() as connection:
        connection.execute("UPDATE approval_requests SET status='executing' WHERE id=?", (approval_id,))
    assert first.vault.get_value(f"approval_payload.{approval_id}")

    restarted = DummyRegistry(tmp_path)
    register(restarted)

    approval = restarted.db.get_approval(approval_id)
    assert approval["status"] == "failed"
    assert "interrupted" in str(approval.get("result", {})).lower()
    assert restarted.invocations == []
    _assert_payload_deleted(restarted, approval_id)
