from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.db import Database
from app.secure_database import SecureDatabase


def test_database_import_uses_secure_boundary() -> None:
    assert Database is SecureDatabase


def test_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    db = Database(tmp_path / "data.sqlite3")
    with pytest.raises(RuntimeError):
        with db.connect() as connection:
            connection.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at) VALUES (?,?,?,?)",
                ("rolled-back", "rollback", "now", "now"),
            )
            raise RuntimeError("abort transaction")
    with db.connect() as connection:
        row = connection.execute("SELECT id FROM conversations WHERE id='rolled-back'").fetchone()
    assert row is None


def test_audit_redacts_embedded_credentials(tmp_path: Path) -> None:
    db = Database(tmp_path / "data.sqlite3")
    db.audit(
        "security.test",
        "request failed Bearer super-secret-token",
        {"password": "db-password", "detail": "api_key=inline-secret"},
    )
    with db.connect() as connection:
        row = connection.execute("SELECT summary,metadata_json FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    persisted = row["summary"] + row["metadata_json"]
    assert "super-secret-token" not in persisted
    assert "db-password" not in persisted
    assert "inline-secret" not in persisted
    assert "redacted" in persisted


def test_webhook_payload_is_redacted_and_bounded(tmp_path: Path) -> None:
    db = Database(tmp_path / "data.sqlite3")
    result = db.add_webhook_event(
        "provider.event",
        {"access_token": "webhook-secret", "message": "visible", "Authorization": "Bearer another-secret"},
    )
    assert result["payload"]["access_token"] == "[redacted]"
    with db.connect() as connection:
        row = connection.execute("SELECT payload_json FROM webhook_events WHERE id=?", (result["id"],)).fetchone()
    assert row is not None
    persisted = row["payload_json"]
    assert "webhook-secret" not in persisted
    assert "another-secret" not in persisted
    payload = json.loads(persisted)
    assert payload["message"] == "visible"


def test_database_symlink_is_rejected(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    real = tmp_path / "real.sqlite3"
    base = SecureDatabase(real)
    del base
    linked = tmp_path / "linked.sqlite3"
    try:
        linked.symlink_to(real)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        SecureDatabase(linked)


def test_posix_database_permissions_are_private(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX permissions only")
    database = tmp_path / "private.sqlite3"
    db = Database(database)
    with db.connect() as connection:
        connection.execute("SELECT 1")
    assert database.stat().st_mode & 0o777 == 0o600
