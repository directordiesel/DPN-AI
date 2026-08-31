from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class SandboxManager:
    """Bounded code execution using Docker when available.

    Host fallback is intentionally opt-in because a subprocess is not a security
    boundary. Docker runs with no network, a read-only root filesystem, memory
    and CPU limits, and a writable per-run workspace mount.
    """

    def __init__(self, workspace: Path, allow_host_fallback: bool = False):
        self.workspace = workspace.resolve()
        self.root = self.workspace / "generated" / "sandboxes"
        self.root.mkdir(parents=True, exist_ok=True)
        self.allow_host_fallback = allow_host_fallback

    @staticmethod
    def _docker_available() -> bool:
        executable = shutil.which("docker")
        if not executable:
            return False
        try:
            result = subprocess.run([executable, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=5, check=False)
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        return {
            "ok": True, "docker_available": self._docker_available(),
            "host_fallback_enabled": self.allow_host_fallback,
            "warning": "Host fallback is a bounded subprocess, not a security isolation boundary.",
            "supported_languages": ["python"],
        }

    @staticmethod
    def _run_id(code: str) -> str:
        return f"run-{int(time.time())}-{hashlib.sha256(code.encode('utf-8')).hexdigest()[:10]}"

    def run_python(self, code: str, timeout_seconds: int = 30, memory_mb: int = 512,
                   network: bool = False, use_host_fallback: bool = False) -> dict[str, Any]:
        timeout_seconds = max(1, min(int(timeout_seconds), 300))
        memory_mb = max(64, min(int(memory_mb), 4096))
        if len(code) > 500_000:
            return {"ok": False, "error": "Sandbox source exceeds 500,000 characters"}
        if network:
            return {"ok": False, "error": "Network access is disabled for code sandboxes. Use an approval-controlled connector or MCP tool instead."}
        run_id = self._run_id(code)
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        source = run_dir / "main.py"
        source.write_text(code, encoding="utf-8")
        started = time.monotonic()
        engine = "docker" if self._docker_available() else "host"
        if engine == "docker":
            command = [
                "docker", "run", "--rm", "--read-only", "--pids-limit", "128",
                "--memory", f"{memory_mb}m", "--cpus", "1.0", "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "--network", "bridge" if network else "none",
                "-v", f"{run_dir}:/work:rw", "-w", "/work", "python:3.12-slim",
                "python", "-I", "main.py",
            ]
        elif self.allow_host_fallback and use_host_fallback:
            command = [sys.executable, "-I", str(source)]
        else:
            return {
                "ok": False, "error": "Docker is unavailable and host fallback is disabled.",
                "run_id": run_id, "path": run_dir.relative_to(self.workspace).as_posix(),
            }
        try:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
            result = subprocess.run(command, cwd=run_dir, capture_output=True, text=True, timeout=timeout_seconds, env=env, check=False)
            stdout = result.stdout[-50_000:]
            stderr = result.stderr[-50_000:]
            record = {
                "engine": engine, "command": command[0:4] + ["…"], "exit_code": result.returncode,
                "stdout": stdout, "stderr": stderr, "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            (run_dir / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            return {
                "ok": result.returncode == 0, "run_id": run_id, "engine": engine,
                "exit_code": result.returncode, "stdout": stdout, "stderr": stderr,
                "elapsed_seconds": record["elapsed_seconds"], "path": run_dir.relative_to(self.workspace).as_posix(),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False, "run_id": run_id, "engine": engine, "error": "Sandbox execution timed out",
                "stdout": (exc.stdout or "")[-50_000:] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[-50_000:] if isinstance(exc.stderr, str) else "",
                "path": run_dir.relative_to(self.workspace).as_posix(),
            }