from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.database_maintenance import DatabaseMaintenance


def make_database(path: Path, value: str = "DPN AI") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))


def read_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM sample ORDER BY id LIMIT 1").fetchone()
    assert row is not None
    return str(row[0])


def test_integrity_check_and_verified_backup(tmp_path: Path) -> None:
    database = tmp_path / "data" / "dpn_ai.sqlite3"
    backups = tmp_path / "data" / "database_backups"
    make_database(database)
    maintenance = DatabaseMaintenance(database, backups)

    assert maintenance.integrity_check()["ok"] is True
    result = maintenance.backup("manual-test")
    assert result["ok"] is True
    assert result["integrity"] == "ok"
    assert (backups / result["path"]).exists()
    assert maintenance.verify_backup(result["path"])["ok"] is True


def test_backup_refuses_overwrite(tmp_path: Path) -> None:
    database = tmp_path / "data" / "dpn_ai.sqlite3"
    backups = tmp_path / "data" / "database_backups"
    make_database(database)
    maintenance = DatabaseMaintenance(database, backups)
    maintenance.backup("same-name")
    with pytest.raises(FileExistsError):
        maintenance.backup("same-name")


def test_database_source_symlink_is_rejected(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    real_database = tmp_path / "real.sqlite3"
    make_database(real_database)
    linked_database = tmp_path / "linked.sqlite3"
    try:
        linked_database.symlink_to(real_database)
    except OSError:
        pytest.skip("symlink creation unavailable")
    maintenance = DatabaseMaintenance(linked_database, tmp_path / "backups")
    with pytest.raises(ValueError):
        maintenance.integrity_check()


def test_backup_directory_symlink_is_rejected(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    database = tmp_path / "data" / "dpn_ai.sqlite3"
    make_database(database)
    real_backups = tmp_path / "real-backups"
    real_backups.mkdir()
    linked_backups = tmp_path / "linked-backups"
    try:
        linked_backups.symlink_to(real_backups, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    maintenance = DatabaseMaintenance(database, linked_backups)
    with pytest.raises(ValueError):
        maintenance.backup("blocked")


def test_backup_name_cannot_escape_private_directory(tmp_path: Path) -> None:
    database = tmp_path / "data" / "dpn_ai.sqlite3"
    backups = tmp_path / "data" / "database_backups"
    make_database(database)
    maintenance = DatabaseMaintenance(database, backups)
    result = maintenance.backup("../../outside")
    target = (backups / result["path"]).resolve()
    target.relative_to(backups.resolve())
    assert not (tmp_path / "outside.sqlite3").exists()


def test_restore_uses_verified_backup_and_preserves_previous_database(tmp_path: Path) -> None:
    database = tmp_path / "data" / "dpn_ai.sqlite3"
    backups = tmp_path / "data" / "database_backups"
    make_database(database, "original")
    maintenance = DatabaseMaintenance(database, backups)
    backup = maintenance.backup("known-good")

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sample SET value='changed'")
    assert read_value(database) == "changed"

    restored = maintenance.restore(backup["path"])
    assert restored["ok"] is True
    assert restored["integrity"] == "ok"
    assert read_value(database) == "original"
    preserved = backups / restored["preserved_previous"]
    assert preserved.exists()
    assert read_value(preserved) == "changed"


def test_restore_rejects_corrupt_backup_without_touching_database(tmp_path: Path) -> None:
    database = tmp_path / "data" / "dpn_ai.sqlite3"
    backups = tmp_path / "data" / "database_backups"
    make_database(database, "keep-me")
    backups.mkdir(parents=True)
    corrupt = backups / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    maintenance = DatabaseMaintenance(database, backups)

    with pytest.raises(sqlite3.DatabaseError):
        maintenance.restore(corrupt.name)
    assert read_value(database) == "keep-me"
