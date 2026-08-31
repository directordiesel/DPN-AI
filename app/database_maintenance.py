from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_BACKUP_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class DatabaseMaintenance:
    """Integrity, backup, and local-permission maintenance for the DPN AI SQLite database."""

    def __init__(self, database_path: Path, backup_dir: Path):
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)

    @staticmethod
    def _reject_symlink_components(path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError(f"Symlinked database path component is not allowed: {current}")

    def _source(self) -> Path:
        self._reject_symlink_components(self.database_path.parent)
        if self.database_path.is_symlink():
            raise ValueError("Database file must not be a symlink")
        if not self.database_path.exists() or not self.database_path.is_file():
            raise FileNotFoundError("DPN AI database file does not exist")
        return self.database_path

    def _backup_root(self) -> Path:
        self._reject_symlink_components(self.backup_dir.parent)
        if self.backup_dir.exists() and self.backup_dir.is_symlink():
            raise ValueError("Database backup directory must not be a symlink")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._chmod_private(self.backup_dir, directory=True)
        return self.backup_dir

    @staticmethod
    def _chmod_private(path: Path, *, directory: bool = False) -> None:
        if os.name == "posix":
            try:
                path.chmod(0o700 if directory else 0o600)
            except OSError:
                pass

    @staticmethod
    def _check_connection(connection: sqlite3.Connection, *, full: bool = False) -> list[str]:
        pragma = "integrity_check" if full else "quick_check"
        rows = connection.execute(f"PRAGMA {pragma}").fetchall()
        return [str(row[0]) for row in rows]

    def integrity_check(self, *, full: bool = False) -> dict[str, Any]:
        source = self._source()
        with sqlite3.connect(source, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            details = self._check_connection(connection, full=full)
        ok = details == ["ok"]
        return {
            "ok": ok,
            "check": "integrity_check" if full else "quick_check",
            "database": source.name,
            "size_bytes": source.stat().st_size,
            "details": details[:100],
        }

    def harden_permissions(self) -> dict[str, Any]:
        source = self._source()
        touched: list[str] = []
        for candidate in (source, Path(f"{source}-wal"), Path(f"{source}-shm")):
            if candidate.exists() and not candidate.is_symlink():
                self._chmod_private(candidate)
                touched.append(candidate.name)
        root = self._backup_root()
        return {"ok": True, "files": touched, "backup_dir": root.name}

    def _safe_backup_name(self, name: str | None) -> str:
        if name:
            cleaned = _BACKUP_NAME.sub("-", name.strip()).strip(".-")[:80]
        else:
            cleaned = ""
        if not cleaned:
            cleaned = datetime.now(timezone.utc).strftime("dpn-ai-%Y%m%dT%H%M%SZ")
        if not cleaned.lower().endswith((".sqlite3", ".db")):
            cleaned += ".sqlite3"
        return cleaned

    def backup(self, name: str | None = None) -> dict[str, Any]:
        source = self._source()
        root = self._backup_root()
        target = root / self._safe_backup_name(name)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Database backup already exists: {target.name}")

        fd, temporary_name = tempfile.mkstemp(prefix=".dpn-ai-db-", suffix=".tmp", dir=root)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            self._chmod_private(temporary)
            with sqlite3.connect(source, timeout=30) as source_db:
                source_db.execute("PRAGMA busy_timeout=30000")
                source_db.execute("PRAGMA wal_checkpoint(PASSIVE)")
                with sqlite3.connect(temporary, timeout=30) as backup_db:
                    source_db.backup(backup_db, pages=256, sleep=0.01)
                    backup_db.execute("PRAGMA foreign_keys=ON")
                    details = self._check_connection(backup_db, full=True)
                    if details != ["ok"]:
                        raise sqlite3.DatabaseError(f"Backup integrity check failed: {details[:5]}")
            os.replace(temporary, target)
            self._chmod_private(target)
            return {
                "ok": True,
                "path": target.name,
                "size_bytes": target.stat().st_size,
                "integrity": "ok",
            }
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def verify_backup(self, name: str, *, full: bool = True) -> dict[str, Any]:
        root = self._backup_root().resolve()
        candidate = root / Path(name).name
        if candidate.is_symlink():
            raise ValueError("Database backup must not be a symlink")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Database backup path escaped the backup directory") from exc
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError("Database backup not found")
        with sqlite3.connect(resolved, timeout=30) as connection:
            connection.execute("PRAGMA query_only=ON")
            details = self._check_connection(connection, full=full)
        return {
            "ok": details == ["ok"],
            "path": resolved.name,
            "size_bytes": resolved.stat().st_size,
            "details": details[:100],
        }
