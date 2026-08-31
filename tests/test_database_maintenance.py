from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.database_maintenance import DatabaseMaintenance


def make_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", ("DPN AI",))


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
