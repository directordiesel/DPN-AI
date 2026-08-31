from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class ArchiveTools:
    """Bounded ZIP/TAR inspection and extraction inside the workspace."""

    SUPPORTED = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"}

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.output_dir = self.workspace / "generated" / "extracted"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        target = (self.workspace / path).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Archive path is outside the workspace") from exc
        return target

    @staticmethod
    def _safe_member(name: str) -> bool:
        normalized = PurePosixPath(name.replace("\\", "/"))
        return not normalized.is_absolute() and ".." not in normalized.parts and not (normalized.parts and ":" in normalized.parts[0])

    def inspect(self, path: str, limit: int = 2000) -> dict[str, Any]:
        target = self._resolve(path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": "Archive not found"}
        limit = max(1, min(int(limit), 10000))
        entries: list[dict[str, Any]] = []
        total_size = 0
        unsafe = []
        try:
            if zipfile.is_zipfile(target):
                with zipfile.ZipFile(target) as archive:
                    for item in archive.infolist()[:limit]:
                        safe = self._safe_member(item.filename)
                        if not safe:
                            unsafe.append(item.filename)
                        total_size += int(item.file_size)
                        entries.append({"path": item.filename, "size_bytes": item.file_size, "compressed_bytes": item.compress_size, "directory": item.is_dir(), "safe": safe})
                    count = len(archive.infolist())
                    kind = "zip"
            elif tarfile.is_tarfile(target):
                with tarfile.open(target, "r:*") as archive:
                    members = archive.getmembers()
                    for item in members[:limit]:
                        safe = self._safe_member(item.name) and not item.issym() and not item.islnk() and not item.isdev()
                        if not safe:
                            unsafe.append(item.name)
                        total_size += int(item.size or 0)
                        entries.append({"path": item.name, "size_bytes": item.size, "directory": item.isdir(), "safe": safe, "type": item.type.decode(errors="ignore") if isinstance(item.type, bytes) else str(item.type)})
                    count = len(members)
                    kind = "tar"
            else:
                return {"ok": False, "error": "Only ZIP and TAR-compatible archives are supported"}
        except Exception as exc:
            return {"ok": False, "error": f"Unable to inspect archive: {type(exc).__name__}: {exc}"}
        return {"ok": True, "path": target.relative_to(self.workspace).as_posix(), "kind": kind, "count": count, "shown": len(entries), "total_uncompressed_bytes": total_size, "unsafe_entries": unsafe[:100], "entries": entries}

    def extract(self, path: str, destination: str | None = None, max_files: int = 5000, max_bytes: int = 2_000_000_000, overwrite: bool = False) -> dict[str, Any]:
        target = self._resolve(path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": "Archive not found"}
        destination_name = Path(destination).name if destination else target.stem
        output = (self.output_dir / destination_name).resolve()
        try:
            output.relative_to(self.workspace)
        except ValueError:
            return {"ok": False, "error": "Extraction destination is outside the workspace"}
        report = self.inspect(path, limit=max_files + 1)
        if not report.get("ok"):
            return report
        if report["count"] > max_files:
            return {"ok": False, "error": f"Archive has {report['count']} entries; limit is {max_files}"}
        if report["total_uncompressed_bytes"] > max_bytes:
            return {"ok": False, "error": f"Archive expands to more than {max_bytes} bytes"}
        if report["unsafe_entries"]:
            return {"ok": False, "error": "Archive contains unsafe paths, links, or device entries", "unsafe_entries": report["unsafe_entries"]}
        if output.exists():
            if not overwrite:
                return {"ok": False, "error": "Destination already exists. Set overwrite=true to replace it."}
            shutil.rmtree(output)
        output.mkdir(parents=True, exist_ok=True)
        try:
            if report["kind"] == "zip":
                with zipfile.ZipFile(target) as archive:
                    for item in archive.infolist():
                        member_target = (output / item.filename).resolve()
                        member_target.relative_to(output)
                        if item.is_dir():
                            member_target.mkdir(parents=True, exist_ok=True)
                        else:
                            member_target.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(item) as source, member_target.open("wb") as dest:
                                shutil.copyfileobj(source, dest)
            else:
                with tarfile.open(target, "r:*") as archive:
                    for item in archive.getmembers():
                        member_target = (output / item.name).resolve()
                        member_target.relative_to(output)
                        if item.isdir():
                            member_target.mkdir(parents=True, exist_ok=True)
                        elif item.isfile():
                            member_target.parent.mkdir(parents=True, exist_ok=True)
                            source = archive.extractfile(item)
                            if source:
                                with source, member_target.open("wb") as dest:
                                    shutil.copyfileobj(source, dest)
        except Exception as exc:
            shutil.rmtree(output, ignore_errors=True)
            return {"ok": False, "error": f"Extraction failed: {type(exc).__name__}: {exc}"}
        return {"ok": True, "path": output.relative_to(self.workspace).as_posix(), "files": report["count"], "bytes": report["total_uncompressed_bytes"]}