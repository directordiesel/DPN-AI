from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".jsonc", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".html", ".css", ".scss", ".sql", ".lua", ".xml", ".csv",
    ".bat", ".cmd", ".ps1", ".sh", ".java", ".cs", ".cpp", ".c", ".h", ".hpp", ".go", ".rs",
    ".vue", ".svelte", ".php", ".rb", ".gradle", ".properties",
}
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build"}


class WorkspaceFS:
    def __init__(self, root: Path, max_read_bytes: int = 2_000_000):
        self.root = root.resolve()
        self.max_read_bytes = max_read_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str) -> Path:
        cleaned = (relative_path or ".").strip().replace("\\", "/").lstrip("/")
        candidate = (self.root / cleaned).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escapes the DPN AI workspace") from exc
        return candidate

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    @staticmethod
    def _ignored(item: Path) -> bool:
        return any(part in IGNORED_DIRS for part in item.parts)

    def list_files(self, path: str = ".", pattern: str = "*", recursive: bool = True, limit: int = 500) -> dict[str, Any]:
        base = self.resolve(path)
        if not base.exists():
            return {"ok": False, "error": f"Path does not exist: {path}"}
        if base.is_file():
            return {"ok": True, "entries": [{"path": self.relative(base), "type": "file", "size_bytes": base.stat().st_size}], "count": 1}
        iterator = base.rglob("*") if recursive else base.glob("*")
        results: list[dict[str, Any]] = []
        for item in iterator:
            if self._ignored(item):
                continue
            rel = self.relative(item)
            if not fnmatch.fnmatch(item.name, pattern) and not fnmatch.fnmatch(rel, pattern):
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            results.append({
                "path": rel,
                "type": "directory" if item.is_dir() else "file",
                "size_bytes": 0 if item.is_dir() else stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            })
            if len(results) >= max(1, min(limit, 5000)):
                break
        results.sort(key=lambda entry: (entry["type"] != "directory", entry["path"].lower()))
        return {"ok": True, "entries": results, "count": len(results)}

    def directory_tree(self, path: str = ".", max_depth: int = 4, max_entries: int = 700) -> dict[str, Any]:
        base = self.resolve(path)
        if not base.exists() or not base.is_dir():
            return {"ok": False, "error": f"Directory does not exist: {path}"}
        lines = [f"{self.relative(base) or '.'}/"]
        count = 0
        for item in sorted(base.rglob("*"), key=lambda p: (p.is_file(), p.as_posix().lower())):
            if self._ignored(item):
                continue
            depth = len(item.relative_to(base).parts)
            if depth > max(1, min(max_depth, 12)):
                continue
            prefix = "  " * depth + ("└─ " if item.is_file() else "▸ ")
            lines.append(prefix + item.name + ("/" if item.is_dir() else ""))
            count += 1
            if count >= max(1, min(max_entries, 3000)):
                lines.append("… tree truncated …")
                break
        return {"ok": True, "path": self.relative(base), "tree": "\n".join(lines), "entries": count}

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": f"File does not exist: {path}"}
        size = target.stat().st_size
        if size > self.max_read_bytes:
            return {"ok": False, "error": f"File is too large to read directly ({size} bytes)"}
        if target.suffix.lower() not in TEXT_EXTENSIONS and target.suffix.lower() not in {""}:
            return {"ok": False, "error": "Binary file. Use document indexing or download it from the Files panel."}
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(start_line, 1)
        end = len(lines) if end_line is None else max(start, min(end_line, len(lines)))
        selected = lines[start - 1:end]
        numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start=start))
        return {"ok": True, "path": self.relative(target), "start_line": start, "end_line": end, "total_lines": len(lines), "content": numbered}

    def search_text(self, query: str, path: str = ".", pattern: str = "*", case_sensitive: bool = False, limit: int = 100) -> dict[str, Any]:
        base = self.resolve(path)
        if not base.exists():
            return {"ok": False, "error": f"Path does not exist: {path}"}
        needle = query if case_sensitive else query.lower()
        candidates = [base] if base.is_file() else base.rglob("*")
        matches: list[dict[str, Any]] = []
        for candidate in candidates:
            if not candidate.is_file() or self._ignored(candidate):
                continue
            if candidate.suffix.lower() not in TEXT_EXTENSIONS and candidate.suffix != "":
                continue
            rel = self.relative(candidate)
            if not fnmatch.fnmatch(candidate.name, pattern) and not fnmatch.fnmatch(rel, pattern):
                continue
            try:
                if candidate.stat().st_size > self.max_read_bytes:
                    continue
                for line_number, line in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    haystack = line if case_sensitive else line.lower()
                    if needle in haystack:
                        matches.append({"path": rel, "line": line_number, "content": line[:1000]})
                        if len(matches) >= max(1, min(limit, 1000)):
                            return {"ok": True, "query": query, "matches": matches, "count": len(matches), "truncated": True}
            except OSError:
                continue
        return {"ok": True, "query": query, "matches": matches, "count": len(matches), "truncated": False}

    def write_file(self, path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
        target = self.resolve(path)
        if target.exists() and not overwrite:
            return {"ok": False, "error": f"File already exists: {path}"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return {"ok": True, "path": self.relative(target), "bytes_written": target.stat().st_size, "sha256": self.file_hash(self.relative(target))["sha256"]}

    def replace_text(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": f"File does not exist: {path}"}
        text = target.read_text(encoding="utf-8", errors="strict")
        count = text.count(old_text)
        if count == 0:
            return {"ok": False, "error": "The exact old_text was not found"}
        if count > 1 and not replace_all:
            return {"ok": False, "error": f"old_text occurs {count} times; set replace_all=true or provide more context"}
        updated = text.replace(old_text, new_text, -1 if replace_all else 1)
        target.write_text(updated, encoding="utf-8", newline="\n")
        return {"ok": True, "path": self.relative(target), "replacements": count if replace_all else 1, "sha256": self.file_hash(self.relative(target))["sha256"]}

    def copy_path(self, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src = self.resolve(source)
        dst = self.resolve(destination)
        if not src.exists():
            return {"ok": False, "error": f"Source does not exist: {source}"}
        if dst.exists() and not overwrite:
            return {"ok": False, "error": f"Destination already exists: {destination}"}
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists() and not dst.is_dir():
                return {"ok": False, "error": "Source is a directory but destination is a file"}
            shutil.copytree(src, dst, dirs_exist_ok=overwrite)
        else:
            if dst.exists() and dst.is_dir():
                return {"ok": False, "error": "Source is a file but destination is a directory"}
            shutil.copy2(src, dst)
        return {"ok": True, "source": self.relative(src), "path": self.relative(dst)}

    def file_hash(self, path: str, algorithm: str = "sha256") -> dict[str, Any]:
        target = self.resolve(path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": f"File does not exist: {path}"}
        if algorithm not in hashlib.algorithms_available:
            return {"ok": False, "error": f"Unsupported hash algorithm: {algorithm}"}
        digest = hashlib.new(algorithm)
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"ok": True, "path": self.relative(target), "algorithm": algorithm, algorithm: digest.hexdigest(), "size_bytes": target.stat().st_size}

    def make_directory(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": self.relative(target)}

    def delete_path(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        if target == self.root:
            return {"ok": False, "error": "Cannot delete the workspace root"}
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {path}"}
        if target.is_dir():
            if any(target.iterdir()):
                return {"ok": False, "error": "Directory is not empty; DPN AI will not recursively delete it"}
            target.rmdir()
        else:
            target.unlink()
        return {"ok": True, "deleted": self.relative(target) if target.exists() else path}

    def upload_bytes(self, filename: str, data: bytes, destination: str = "uploads") -> str:
        safe_name = Path(filename).name
        target_dir = self.resolve(destination)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        stem, suffix = target.stem, target.suffix
        counter = 1
        while target.exists():
            target = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        target.write_bytes(data)
        return self.relative(target)

    def disk_summary(self) -> dict[str, Any]:
        files = 0
        directories = 0
        total = 0
        extensions: dict[str, int] = {}
        for root, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            directories += len(dirs)
            for name in names:
                path = Path(root) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files += 1
                total += stat.st_size
                suffix = path.suffix.lower() or "[no extension]"
                extensions[suffix] = extensions.get(suffix, 0) + 1
        top_extensions = dict(sorted(extensions.items(), key=lambda item: item[1], reverse=True)[:12])
        return {"root": str(self.root), "files": files, "directories": directories, "bytes": total, "top_extensions": top_extensions}