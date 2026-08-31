from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any


BLOCKED_TOKENS = {
    "rm", "rmdir", "del", "erase", "format", "diskpart", "shutdown", "reboot", "halt", "poweroff",
    "reg", "takeown", "icacls", "net", "netsh", "sc", "schtasks", "bcdedit", "cipher", "mount", "umount",
    "sudo", "su", "curl", "wget", "Invoke-WebRequest", "Start-BitsTransfer",
}

ALLOWED_EXECUTABLES = {
    "python", "python3", "py", "pytest", "ruff", "mypy", "pip", "pip3", "uv",
    "git", "node", "npm", "npx", "pnpm", "bun", "deno",
    "go", "cargo", "rustc", "dotnet", "java", "javac", "lua",
}


class SafeCommandRunner:
    def __init__(self, workspace: Path, timeout_seconds: int = 90, output_limit: int = 24_000):
        self.workspace = workspace.resolve()
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit

    def _resolve_cwd(self, cwd: str) -> Path:
        target = (self.workspace / cwd.strip().lstrip("/\\")).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Working directory escapes the workspace") from exc
        target.mkdir(parents=True, exist_ok=True)
        return target

    def run(self, command: str, cwd: str = ".", timeout_seconds: int | None = None) -> dict[str, Any]:
        if not command.strip():
            return {"ok": False, "error": "Command is empty"}
        try:
            args = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            return {"ok": False, "error": f"Cannot parse command: {exc}"}
        if not args:
            return {"ok": False, "error": "Command is empty"}
        executable = Path(args[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        if executable not in ALLOWED_EXECUTABLES:
            return {
                "ok": False,
                "error": f"Executable '{executable}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXECUTABLES))}",
            }
        lowered = {part.lower() for part in args}
        if lowered.intersection({token.lower() for token in BLOCKED_TOKENS}):
            return {"ok": False, "error": "Command contains a blocked system-management token"}
        if executable in {"python", "python3", "py"} and any(part in {"-c", "-m"} for part in args[1:]):
            return {"ok": False, "error": "Inline Python and python -m are blocked. Write a script in the workspace first."}
        if executable in {"node", "deno", "bun"} and any(part in {"-e", "--eval"} for part in args[1:]):
            return {"ok": False, "error": "Inline JavaScript execution is blocked. Write a script first."}

        workdir = self._resolve_cwd(cwd)
        timeout = max(5, min(timeout_seconds or self.timeout_seconds, 600))
        env = os.environ.copy()
        env["DPN_AI_WORKSPACE"] = str(self.workspace)
        env["PYTHONUNBUFFERED"] = "1"
        started = time.monotonic()
        try:
            process = subprocess.run(
                args,
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                errors="replace",
            )
        except FileNotFoundError:
            return {"ok": False, "error": f"Executable not found: {args[0]}"}
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "")[-self.output_limit:]
            stderr = (exc.stderr or "")[-self.output_limit:]
            return {"ok": False, "error": f"Command timed out after {timeout}s", "stdout": stdout, "stderr": stderr}
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout = process.stdout[-self.output_limit:]
        stderr = process.stderr[-self.output_limit:]
        return {
            "ok": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_ms": elapsed_ms,
            "cwd": str(workdir.relative_to(self.workspace)) or ".",
        }