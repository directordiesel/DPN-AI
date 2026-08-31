from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


MAX_SOURCE_BYTES = 500_000
OUTPUT_LIMIT_BYTES = 50_000
SANDBOX_IMAGE = "python:3.12-slim"


class SandboxManager:
    """Bounded code execution using Docker when available.

    Host fallback is intentionally opt-in because a subprocess is not a security
    boundary. Docker runs with no network, a read-only root filesystem, memory
    and CPU limits, and a writable per-run workspace mount.
    """

    def __init__(self, workspace: Path, allow_host_fallback: bool = False):
        workspace.mkdir(parents=True, exist_ok=True)
        self.workspace = workspace.resolve()
        generated = self.workspace / "generated"
        self._ensure_private_directory(generated)
        self.root = generated / "sandboxes"
        self._ensure_private_directory(self.root)
        self.allow_host_fallback = allow_host_fallback

    def _ensure_private_directory(self, path: Path) -> None:
        if path.is_symlink():
            raise ValueError(f"Sandbox directory must not be a symlink: {path}")
        path.mkdir(parents=False, exist_ok=True)
        resolved = path.resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Sandbox directory escapes the workspace") from exc
        if not resolved.is_dir():
            raise ValueError(f"Sandbox path is not a directory: {path}")

    @staticmethod
    def _docker_executable() -> str | None:
        executable = shutil.which("docker")
        return str(Path(executable).resolve()) if executable else None

    @classmethod
    def _docker_available(cls) -> bool:
        executable = cls._docker_executable()
        if not executable:
            return False
        try:
            result = subprocess.run(
                [executable, "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "docker_available": self._docker_available(),
            "host_fallback_enabled": self.allow_host_fallback,
            "warning": "Host fallback is a bounded subprocess, not a security isolation boundary.",
            "supported_languages": ["python"],
            "sandbox_image": SANDBOX_IMAGE,
            "network_enabled": False,
        }

    @staticmethod
    def _run_id(code: str) -> str:
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:10]
        return f"run-{time.time_ns()}-{digest}-{secrets.token_hex(3)}"

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        temp = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        SandboxManager._write_exclusive(temp, data)
        try:
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _bounded_process(
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
    ) -> tuple[int | None, str, str, bool]:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        stdout_tail = bytearray()
        stderr_tail = bytearray()

        def drain(stream: Any, target: bytearray) -> None:
            if stream is None:
                return
            try:
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        break
                    target.extend(chunk)
                    if len(target) > OUTPUT_LIMIT_BYTES:
                        del target[:-OUTPUT_LIMIT_BYTES]
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        threads = [
            threading.Thread(target=drain, args=(process.stdout, stdout_tail), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr_tail), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=5)
        finally:
            for thread in threads:
                thread.join(timeout=5)
        return (
            process.returncode,
            bytes(stdout_tail).decode("utf-8", errors="replace"),
            bytes(stderr_tail).decode("utf-8", errors="replace"),
            timed_out,
        )

    def run_python(
        self,
        code: str,
        timeout_seconds: int = 30,
        memory_mb: int = 512,
        network: bool = False,
        use_host_fallback: bool = False,
    ) -> dict[str, Any]:
        timeout_seconds = max(1, min(int(timeout_seconds), 300))
        memory_mb = max(64, min(int(memory_mb), 4096))
        source_bytes = code.encode("utf-8")
        if len(source_bytes) > MAX_SOURCE_BYTES:
            return {"ok": False, "error": f"Sandbox source exceeds {MAX_SOURCE_BYTES:,} bytes"}
        if network:
            return {
                "ok": False,
                "error": "Network access is disabled for code sandboxes. Use an approval-controlled connector or MCP tool instead.",
            }

        run_id = self._run_id(code)
        run_dir = self.root / run_id
        run_dir.mkdir(parents=False, exist_ok=False, mode=0o700)
        if run_dir.is_symlink():
            raise RuntimeError("Sandbox run directory unexpectedly became a symlink")
        try:
            run_dir.resolve().relative_to(self.root.resolve())
        except ValueError as exc:
            raise RuntimeError("Sandbox run directory escaped the sandbox root") from exc

        source = run_dir / "main.py"
        self._write_exclusive(source, source_bytes)
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        started = time.monotonic()
        docker_executable = self._docker_executable() if self._docker_available() else None
        engine = "docker" if docker_executable else "host"
        container_name = f"dpn-ai-{run_id}"[:63]

        if engine == "docker":
            command = [
                docker_executable,
                "run",
                "--rm",
                "--name",
                container_name,
                "--read-only",
                "--pids-limit",
                "64",
                "--memory",
                f"{memory_mb}m",
                "--cpus",
                "1.0",
                "--security-opt",
                "no-new-privileges",
                "--cap-drop",
                "ALL",
                "--network",
                "none",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=64m",
                "--ulimit",
                "nofile=64:64",
                "-v",
                f"{run_dir}:/work:rw",
                "-w",
                "/work",
                SANDBOX_IMAGE,
                "python",
                "-I",
                "main.py",
            ]
        elif self.allow_host_fallback and use_host_fallback:
            command = [str(Path(sys.executable).resolve()), "-I", str(source)]
        else:
            return {
                "ok": False,
                "error": "Docker is unavailable and host fallback is disabled.",
                "run_id": run_id,
                "path": run_dir.relative_to(self.workspace).as_posix(),
            }

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "HOME": str(run_dir),
        }
        try:
            exit_code, stdout, stderr, timed_out = self._bounded_process(
                command,
                run_dir,
                env,
                timeout_seconds,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "run_id": run_id,
                "engine": engine,
                "error": "Sandbox runtime executable was not found",
                "path": run_dir.relative_to(self.workspace).as_posix(),
            }
        finally:
            if engine == "docker" and docker_executable:
                subprocess.run(
                    [docker_executable, "rm", "-f", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )

        elapsed = round(time.monotonic() - started, 3)
        record = {
            "engine": engine,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_seconds": elapsed,
            "source_sha256": source_sha256,
            "output_limit_bytes": OUTPUT_LIMIT_BYTES,
            "network": False,
        }
        self._atomic_write_json(run_dir / "result.json", record)

        if timed_out:
            return {
                "ok": False,
                "run_id": run_id,
                "engine": engine,
                "error": "Sandbox execution timed out",
                "stdout": stdout,
                "stderr": stderr,
                "elapsed_seconds": elapsed,
                "path": run_dir.relative_to(self.workspace).as_posix(),
            }
        return {
            "ok": exit_code == 0,
            "run_id": run_id,
            "engine": engine,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_seconds": elapsed,
            "path": run_dir.relative_to(self.workspace).as_posix(),
            "source_sha256": source_sha256,
        }
