from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import shutil
import time
from pathlib import Path
from typing import Any


DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
HIGH_RISK_IMPORTS = {"ctypes", "winreg"}


class CapabilityForge:
    """Stage, inspect, validate, promote, and roll back trusted local plugins."""

    def __init__(self, plugins_dir: Path, data_dir: Path):
        self.plugins_dir = plugins_dir.resolve()
        self.staging_dir = data_dir.resolve() / "capability_staging"
        self.backup_dir = data_dir.resolve() / "capability_backups"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_id(value: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned[:80]

    def stage(self, capability_id: str, code: str, description: str = "", overwrite: bool = False) -> dict[str, Any]:
        safe_id = self._safe_id(capability_id)
        if not safe_id:
            return {"ok": False, "error": "Invalid capability id"}
        if len(code) > 1_000_000:
            return {"ok": False, "error": "Capability source exceeds 1 MB"}
        folder = self.staging_dir / safe_id
        if folder.exists() and not overwrite:
            return {"ok": False, "error": "A staged capability with this id already exists"}
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{safe_id}.py"
        target.write_text(code, encoding="utf-8")
        manifest = {
            "id": safe_id, "description": description[:5000], "status": "staged",
            "sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(), "created_at": time.time(),
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"ok": True, "capability": manifest, "path": str(target)}

    def validate(self, capability_id: str) -> dict[str, Any]:
        safe_id = self._safe_id(capability_id)
        folder = self.staging_dir / safe_id
        source = folder / f"{safe_id}.py"
        if not source.is_file():
            return {"ok": False, "error": "Staged capability not found"}
        issues: list[dict[str, Any]] = []
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except SyntaxError as exc:
            return {"ok": False, "valid": False, "issues": [{"severity": "error", "message": str(exc)}]}
        has_register = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "register":
                has_register = True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in HIGH_RISK_IMPORTS:
                        issues.append({"severity": "high", "line": node.lineno, "message": f"High-risk import: {alias.name}"})
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in HIGH_RISK_IMPORTS:
                issues.append({"severity": "high", "line": node.lineno, "message": f"High-risk import: {node.module}"})
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else ""
                if name in DANGEROUS_CALLS:
                    issues.append({"severity": "high", "line": node.lineno, "message": f"Dynamic execution call: {name}"})
        if not has_register:
            issues.append({"severity": "error", "message": "Plugin must define register(registry)."})
        try:
            py_compile.compile(str(source), doraise=True)
        except py_compile.PyCompileError as exc:
            issues.append({"severity": "error", "message": str(exc)})
        valid = not any(item["severity"] in {"error", "high"} for item in issues)
        report = {"ok": True, "valid": valid, "issues": issues, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        (folder / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    def promote(self, capability_id: str) -> dict[str, Any]:
        safe_id = self._safe_id(capability_id)
        validation = self.validate(safe_id)
        if not validation.get("valid"):
            return {"ok": False, "error": "Capability validation failed", "validation": validation}
        source = self.staging_dir / safe_id / f"{safe_id}.py"
        target = self.plugins_dir / f"{safe_id}.py"
        backup = None
        if target.exists():
            stamp = int(time.time())
            backup = self.backup_dir / f"{safe_id}-{stamp}.py"
            shutil.copy2(target, backup)
        shutil.copy2(source, target)
        return {
            "ok": True, "plugin": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "backup": str(backup) if backup else None,
            "restart_required": True,
        }

    def rollback(self, capability_id: str, backup_name: str | None = None) -> dict[str, Any]:
        safe_id = self._safe_id(capability_id)
        candidates = sorted(self.backup_dir.glob(f"{safe_id}-*.py"), key=lambda item: item.stat().st_mtime, reverse=True)
        if backup_name:
            safe_name = Path(backup_name).name
            candidates = [item for item in candidates if item.name == safe_name]
        if not candidates:
            return {"ok": False, "error": "No rollback backup exists for this capability"}
        backup = candidates[0]
        target = self.plugins_dir / f"{safe_id}.py"
        current_backup = None
        if target.exists():
            current_backup = self.backup_dir / f"{safe_id}-{int(time.time())}-pre-rollback.py"
            shutil.copy2(target, current_backup)
        shutil.copy2(backup, target)
        return {
            "ok": True, "plugin": target.name, "restored_from": backup.name,
            "preserved_current": str(current_backup) if current_backup else None,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "restart_required": True,
        }

    def list(self) -> dict[str, Any]:
        staged = []
        for folder in sorted(self.staging_dir.iterdir() if self.staging_dir.exists() else []):
            manifest_path = folder / "manifest.json"
            if folder.is_dir() and manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    manifest = {"id": folder.name, "status": "invalid-manifest"}
                validation_path = folder / "validation.json"
                if validation_path.exists():
                    try:
                        manifest["validation"] = json.loads(validation_path.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                staged.append(manifest)
        active = [path.name for path in sorted(self.plugins_dir.glob("*.py")) if path.name != "__init__.py"]
        backups = [
            {"name": path.name, "size_bytes": path.stat().st_size, "modified_at": path.stat().st_mtime}
            for path in sorted(self.backup_dir.glob("*.py"), key=lambda item: item.stat().st_mtime, reverse=True)
        ]
        return {"ok": True, "staged": staged, "active": active, "backups": backups}