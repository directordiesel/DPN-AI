from __future__ import annotations

import os
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


class ArchiveTools:
    """Bounded ZIP/TAR inspection and extraction inside the workspace."""

    SUPPORTED = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"}
    MAX_FILES = 5000
    MAX_BYTES = 2_000_000_000
    COPY_CHUNK_BYTES = 1024 * 1024

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        generated = self.workspace / "generated"
        output_dir = generated / "extracted"
        if generated.is_symlink() or output_dir.is_symlink():
            raise ValueError("Archive output directories must not be symlinks")
        output_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_dir.resolve()
        try:
            self.output_dir.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Archive output directory escapes the workspace") from exc

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
        return (
            bool(normalized.parts)
            and not normalized.is_absolute()
            and ".." not in normalized.parts
            and not (normalized.parts and ":" in normalized.parts[0])
            and "\x00" not in name
        )

    @staticmethod
    def _zip_member_safe(item: zipfile.ZipInfo) -> bool:
        if not ArchiveTools._safe_member(item.filename):
            return False
        mode = (item.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            return False
        if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            # Some ZIP creators only populate permission bits, so only reject
            # entries that clearly advertise a special file type.
            file_type = stat.S_IFMT(mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                return False
        return True

    @staticmethod
    def _bounded_copy(source: BinaryIO, destination: BinaryIO, remaining: int) -> int:
        written = 0
        while True:
            chunk = source.read(min(ArchiveTools.COPY_CHUNK_BYTES, remaining - written + 1))
            if not chunk:
                return written
            written += len(chunk)
            if written > remaining:
                raise ValueError("Archive exceeded the configured extraction byte limit")
            destination.write(chunk)

    def inspect(self, path: str, limit: int = 2000) -> dict[str, Any]:
        target = self._resolve(path)
        if target.is_symlink() or not target.exists() or not target.is_file():
            return {"ok": False, "error": "Archive not found or is a symlink"}
        limit = max(1, min(int(limit), 10000))
        entries: list[dict[str, Any]] = []
        total_size = 0
        unsafe = []
        try:
            if zipfile.is_zipfile(target):
                with zipfile.ZipFile(target) as archive:
                    members = archive.infolist()
                    for item in members[:limit]:
                        safe = self._zip_member_safe(item)
                        if not safe:
                            unsafe.append(item.filename)
                        total_size += int(item.file_size)
                        entries.append({"path": item.filename, "size_bytes": item.file_size, "compressed_bytes": item.compress_size, "directory": item.is_dir(), "safe": safe})
                    count = len(members)
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
        if target.is_symlink() or not target.exists() or not target.is_file():
            return {"ok": False, "error": "Archive not found or is a symlink"}
        max_files = max(1, min(int(max_files), self.MAX_FILES))
        max_bytes = max(1, min(int(max_bytes), self.MAX_BYTES))
        destination_name = Path(destination).name if destination else target.stem
        if destination_name in {"", ".", ".."}:
            return {"ok": False, "error": "Invalid extraction destination"}
        output = self.output_dir / destination_name
        if output.is_symlink():
            return {"ok": False, "error": "Extraction destination must not be a symlink"}
        output = output.resolve()
        try:
            output.relative_to(self.output_dir)
        except ValueError:
            return {"ok": False, "error": "Extraction destination is outside the archive output directory"}
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
            if output.is_symlink():
                return {"ok": False, "error": "Extraction destination must not be a symlink"}
            shutil.rmtree(output)
        output.mkdir(parents=True, exist_ok=False)
        extracted_bytes = 0
        try:
            if report["kind"] == "zip":
                with zipfile.ZipFile(target) as archive:
                    for item in archive.infolist():
                        if not self._zip_member_safe(item):
                            raise ValueError(f"Unsafe ZIP member: {item.filename}")
                        member_target = output / item.filename
                        resolved_parent = member_target.parent.resolve()
                        resolved_parent.relative_to(output)
                        if item.is_dir():
                            member_target.mkdir(parents=True, exist_ok=True)
                            continue
                        member_target.parent.mkdir(parents=True, exist_ok=True)
                        if member_target.is_symlink():
                            raise ValueError(f"Refusing symlink extraction target: {item.filename}")
                        with archive.open(item) as source, member_target.open("xb") as dest:
                            extracted_bytes += self._bounded_copy(source, dest, max_bytes - extracted_bytes)
            else:
                with tarfile.open(target, "r:*") as archive:
                    for item in archive.getmembers():
                        if not self._safe_member(item.name) or item.issym() or item.islnk() or item.isdev():
                            raise ValueError(f"Unsafe TAR member: {item.name}")
                        member_target = output / item.name
                        resolved_parent = member_target.parent.resolve()
                        resolved_parent.relative_to(output)
                        if item.isdir():
                            member_target.mkdir(parents=True, exist_ok=True)
                        elif item.isfile():
                            member_target.parent.mkdir(parents=True, exist_ok=True)
                            if member_target.is_symlink():
                                raise ValueError(f"Refusing symlink extraction target: {item.name}")
                            source = archive.extractfile(item)
                            if source:
                                with source, member_target.open("xb") as dest:
                                    extracted_bytes += self._bounded_copy(source, dest, max_bytes - extracted_bytes)
            if extracted_bytes > max_bytes:
                raise ValueError("Archive exceeded the configured extraction byte limit")
        except Exception as exc:
            shutil.rmtree(output, ignore_errors=True)
            return {"ok": False, "error": f"Extraction failed: {type(exc).__name__}: {exc}"}
        return {"ok": True, "path": output.relative_to(self.workspace).as_posix(), "files": report["count"], "bytes": extracted_bytes}
