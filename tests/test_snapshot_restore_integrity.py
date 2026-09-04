from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.services import SnapshotService
from app.tools.filesystem import WorkspaceFS


class StubDB:
    def __init__(self) -> None:
        self.snapshots: dict[str, dict] = {}
        self.audit_events: list[tuple[str, str, dict]] = []

    def add_snapshot(self, name: str, source_path: str, archive_path: str, manifest: dict, size_bytes: int) -> dict:
        snapshot_id = "snapshot-1"
        record = {
            "id": snapshot_id,
            "name": name,
            "source_path": source_path,
            "archive_path": archive_path,
            "manifest": manifest,
            "size_bytes": size_bytes,
        }
        self.snapshots[snapshot_id] = record
        return record

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        return self.snapshots.get(snapshot_id)

    def list_snapshots(self) -> list[dict]:
        return list(self.snapshots.values())

    def audit(self, event_type: str, summary: str, metadata: dict | None = None, actor: str = "system") -> None:
        self.audit_events.append((event_type, summary, metadata or {}))


def make_service(tmp_path: Path) -> tuple[SnapshotService, StubDB, Path]:
    workspace = tmp_path / "workspace"
    snapshots = tmp_path / "snapshots"
    fs = WorkspaceFS(workspace)
    db = StubDB()
    service = SnapshotService(SimpleNamespace(snapshots_dir=snapshots), db, fs)
    return service, db, workspace


def test_valid_snapshot_restores_after_full_integrity_check(tmp_path: Path) -> None:
    service, _db, workspace = make_service(tmp_path)
    target = workspace / "example.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")

    created = service.create("integrity-test")
    assert created["ok"] is True

    target.write_text("changed", encoding="utf-8")
    restored = service.restore(created["id"], overwrite=True)

    assert restored["ok"] is True
    assert restored["restored"] == 1
    assert target.read_text(encoding="utf-8") == "original"


def test_tampered_snapshot_is_rejected_before_any_workspace_write(tmp_path: Path) -> None:
    service, db, workspace = make_service(tmp_path)
    target = workspace / "example.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("trusted-backup", encoding="utf-8")

    created = service.create("integrity-test")
    assert created["ok"] is True

    archive = Path(created["archive_path"])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("example.txt", "tampered-backup")

    target.write_text("current-live-data", encoding="utf-8")
    restored = service.restore(created["id"], overwrite=True)

    assert restored == {"ok": False, "error": "Snapshot archive failed integrity verification"}
    assert target.read_text(encoding="utf-8") == "current-live-data"
    assert db.audit_events[-1][0] == "snapshot.restore_rejected"


def test_snapshot_with_unexpected_file_is_rejected_before_restore(tmp_path: Path) -> None:
    service, _db, workspace = make_service(tmp_path)
    target = workspace / "example.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("trusted-backup", encoding="utf-8")

    created = service.create("integrity-test")
    archive = Path(created["archive_path"])
    with zipfile.ZipFile(archive, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("unexpected.txt", "should-not-restore")

    target.write_text("current-live-data", encoding="utf-8")
    restored = service.restore(created["id"], overwrite=True)

    assert restored == {"ok": False, "error": "Snapshot archive does not match its manifest"}
    assert target.read_text(encoding="utf-8") == "current-live-data"
    assert not (workspace / "unexpected.txt").exists()
