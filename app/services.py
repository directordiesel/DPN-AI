from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db import Database
from app.tools.filesystem import WorkspaceFS


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned[:70] or "snapshot"


class SnapshotService:
    def __init__(self, settings: Settings, db: Database, fs: WorkspaceFS):
        self.settings = settings
        self.db = db
        self.fs = fs
        self.settings.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def create(self, name: str = "manual-snapshot", path: str = ".") -> dict[str, Any]:
        source = self.fs.resolve(path)
        if not source.exists():
            return {"ok": False, "error": f"Path does not exist: {path}"}
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archive = self.settings.snapshots_dir / f"{timestamp}-{_slug(name)}.zip"
        files: list[dict[str, Any]] = []
        candidates = [source] if source.is_file() else source.rglob("*")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                if any(part in {".git", ".venv", "node_modules", "__pycache__"} for part in candidate.parts):
                    continue
                rel = self.fs.relative(candidate)
                stat = candidate.stat()
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                zf.write(candidate, arcname=rel)
                files.append({"path": rel, "size_bytes": stat.st_size, "sha256": digest})
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_path": self.fs.relative(source),
            "file_count": len(files),
            "files": files,
        }
        record = self.db.add_snapshot(
            name=name.strip() or "manual-snapshot",
            source_path=self.fs.relative(source),
            archive_path=str(archive),
            manifest=manifest,
            size_bytes=archive.stat().st_size,
        )
        return {"ok": True, **record}

    def list(self) -> dict[str, Any]:
        snapshots = self.db.list_snapshots()
        for item in snapshots:
            item["archive_exists"] = Path(item["archive_path"]).exists()
        return {"ok": True, "snapshots": snapshots}

    def _validate_restore_archive(self, zf: zipfile.ZipFile, snapshot: dict[str, Any]) -> tuple[bool, str]:
        manifest = snapshot.get("manifest")
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, list) or manifest.get("file_count") != len(files):
            return False, "Snapshot manifest is invalid"

        expected: dict[str, tuple[int, str]] = {}
        for entry in files:
            if not isinstance(entry, dict):
                return False, "Snapshot manifest is invalid"
            path = entry.get("path")
            size = entry.get("size_bytes")
            digest = entry.get("sha256")
            if (
                not isinstance(path, str)
                or not path
                or path in expected
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(ch not in "0123456789abcdefABCDEF" for ch in digest)
            ):
                return False, "Snapshot manifest is invalid"
            try:
                self.fs.resolve(path)
            except ValueError:
                return False, "Snapshot manifest contains an unsafe path"
            expected[path] = (size, digest.lower())

        infos = [info for info in zf.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            return False, "Snapshot archive contains duplicate file entries"
        if set(names) != set(expected):
            return False, "Snapshot archive does not match its manifest"

        for info in infos:
            expected_size, expected_digest = expected[info.filename]
            if info.file_size != expected_size:
                return False, "Snapshot archive failed integrity verification"
            digest = hashlib.sha256()
            actual_size = 0
            with zf.open(info) as src:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    actual_size += len(chunk)
                    digest.update(chunk)
            if actual_size != expected_size or digest.hexdigest() != expected_digest:
                return False, "Snapshot archive failed integrity verification"
        return True, ""

    def restore(self, snapshot_id: str, overwrite: bool = False) -> dict[str, Any]:
        snapshot = self.db.get_snapshot(snapshot_id)
        if not snapshot:
            return {"ok": False, "error": "Snapshot not found"}
        archive = Path(snapshot["archive_path"])
        if not archive.exists():
            return {"ok": False, "error": "Snapshot archive is missing"}
        restored = 0
        skipped = 0
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                valid, error = self._validate_restore_archive(zf, snapshot)
                if not valid:
                    self.db.audit(
                        "snapshot.restore_rejected",
                        f"Rejected snapshot restore {snapshot['name']}",
                        {"snapshot_id": snapshot_id, "reason": error},
                    )
                    return {"ok": False, "error": error}
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    target = self.fs.resolve(info.filename)
                    if target.exists() and not overwrite:
                        skipped += 1
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    restored += 1
        except (OSError, zipfile.BadZipFile, RuntimeError):
            self.db.audit(
                "snapshot.restore_rejected",
                f"Rejected snapshot restore {snapshot['name']}",
                {"snapshot_id": snapshot_id, "reason": "invalid archive"},
            )
            return {"ok": False, "error": "Snapshot archive is invalid or unreadable"}
        self.db.audit("snapshot.restored", f"Restored snapshot {snapshot['name']}", {"snapshot_id": snapshot_id, "restored": restored, "skipped": skipped})
        return {"ok": True, "restored": restored, "skipped": skipped, "overwrite": overwrite}


class ExportService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.settings.exports_dir.mkdir(parents=True, exist_ok=True)

    def conversation(self, conversation_id: str, format: str = "markdown") -> dict[str, Any]:
        conversations = {item["id"]: item for item in self.db.list_conversations(limit=10000)}
        conversation = conversations.get(conversation_id)
        if not conversation:
            return {"ok": False, "error": "Conversation not found"}
        messages = self.db.get_messages(conversation_id, limit=10000)
        slug = _slug(conversation["title"])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if format == "json":
            target = self.settings.exports_dir / f"{stamp}-{slug}.json"
            target.write_text(json.dumps({"conversation": conversation, "messages": messages}, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            target = self.settings.exports_dir / f"{stamp}-{slug}.md"
            lines = [f"# {conversation['title']}", "", f"Exported: {datetime.now(timezone.utc).isoformat()}", ""]
            for message in messages:
                label = "User" if message["role"] == "user" else "DPN AI"
                lines.extend([f"## {label}", "", message["content"], ""])
                metadata = message.get("metadata") or {}
                if metadata.get("generated_files"):
                    lines.extend(["Generated files:", *[f"- `{path}`" for path in metadata["generated_files"]], ""])
            target.write_text("\n".join(lines), encoding="utf-8")
        relative = target.resolve().relative_to(self.settings.workspace_dir).as_posix()
        self.db.audit("conversation.exported", f"Exported conversation {conversation_id}", {"path": relative, "format": format})
        return {"ok": True, "path": relative, "format": format}


class DiagnosticService:
    def __init__(self, settings: Settings, db: Database, fs: WorkspaceFS):
        self.settings = settings
        self.db = db
        self.fs = fs

    def report(self) -> dict[str, Any]:
        disk = shutil.disk_usage(self.settings.workspace_dir)
        memory: dict[str, Any] = {}
        cpu: dict[str, Any] = {"logical_cores": os.cpu_count()}
        try:
            import psutil  # type: ignore
            vm = psutil.virtual_memory()
            memory = {"total_bytes": vm.total, "available_bytes": vm.available, "percent_used": vm.percent}
            cpu["percent"] = psutil.cpu_percent(interval=0.1)
            cpu["physical_cores"] = psutil.cpu_count(logical=False)
        except Exception:
            memory = {"status": "psutil unavailable"}
        with self.db.connect() as connection:
            table_counts = {}
            for table in (
                "conversations", "messages", "memories", "knowledge_documents", "projects",
                "project_tasks", "operation_runs", "automations", "missions", "mission_steps",
                "approval_requests", "semantic_items", "connectors", "workflows", "workflow_runs",
                "webhook_events", "goal_contracts", "graph_nodes", "graph_edges",
                "mission_checkpoints", "evaluation_runs", "background_jobs", "mcp_servers", "mcp_calls",
            ):
                table_counts[table] = int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
        return {
            "ok": True,
            "system": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "architecture": platform.machine(),
                "processor": platform.processor(),
            },
            "cpu": cpu,
            "memory": memory,
            "disk": {"total_bytes": disk.total, "free_bytes": disk.free, "used_bytes": disk.used},
            "workspace": self.fs.disk_summary(),
            "database": {"path": str(self.db.path), "size_bytes": self.db.path.stat().st_size if self.db.path.exists() else 0, "counts": table_counts},
        }
