from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


BLOCKED_TOKENS = {
    "rm", "rmdir", "del", "erase", "format", "diskpart", "shutdown", "reboot", "halt", "poweroff",
    "reg", "takeown", "icacls", "net", "netsh", "sc", "schtasks", "bcdedit", "cipher", "mount", "umount",
    "sudo", "su", "curl", "wget", "invoke-webrequest", "start-bitstransfer",
}

ALLOWED_EXECUTABLES = {
    "python", "python3", "py", "pytest", "ruff", "mypy", "pip", "pip3", "uv",
    "git", "node", "npm", "pnpm", "bun", "deno",
    "go", "cargo", "rustc", "dotnet", "java", "javac", "lua",
}

PACKAGE_MANAGER_BLOCKS: dict[str, set[str]] = {
    "pip": {"install", "download", "wheel"},
    "pip3": {"install", "download", "wheel"},
    "npm": {"install", "i", "add", "ci", "exec", "update"},
    "pnpm": {"install", "add", "dlx", "exec", "update"},
    "bun": {"install", "add", "update", "x"},
    "cargo": {"install"},
    "go": {"install", "get"},
    "uv": {"add", "sync", "pip", "tool"},
}

BLOCKED_GIT_SUBCOMMANDS = {
    "config", "credential", "credential-cache", "credential-store", "submodule", "clean", "gc", "prune", "maintenance",
}
BLOCKED_GIT_ARGUMENT_FRAGMENTS = {
    "core.sshcommand", "protocol.ext", "ext::", "--upload-pack", "--receive-pack", "--config-env", "--exec-path",
}
SENSITIVE_ENV_PREFIXES = (
    "AWS_", "AZURE_", "GCP_", "GOOGLE_", "GITHUB_", "GH_", "OPENAI_", "ANTHROPIC_",
    "HF_", "HUGGINGFACE_", "TWINE_",
)
SENSITIVE_ENV_SUFFIXES = (
    "_TOKEN", "_SECRET", "_PASSWORD", "_API_KEY", "_ACCESS_KEY", "_PRIVATE_KEY", "_COOKIE", "_SESSION",
)
SENSITIVE_ENV_EXACT = {
    "TOKEN", "SECRET", "PASSWORD", "API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN", "PRIVATE_KEY", "CREDENTIALS",
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

    @staticmethod
    def _sensitive_env_name(name: str) -> bool:
        upper = name.upper()
        return (
            upper in SENSITIVE_ENV_EXACT
            or upper.startswith(SENSITIVE_ENV_PREFIXES)
            or upper.endswith(SENSITIVE_ENV_SUFFIXES)
            or "_CREDENTIAL" in upper
        )

    def _safe_environment(self) -> dict[str, str]:
        env = {name: value for name, value in os.environ.items() if not self._sensitive_env_name(name)}
        env["DPN_AI_WORKSPACE"] = str(self.workspace)
        env["PYTHONUNBUFFERED"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        return env

    def _resolve_executable(self, token: str, executable: str) -> tuple[bool, str]:
        if Path(token).is_absolute() or "/" in token or "\\" in token:
            return False, "Executable must be invoked by an allow-listed bare name"
        resolved = shutil.which(token)
        if not resolved:
            return False, f"Executable not found: {token}"
        resolved_path = Path(resolved).resolve()
        try:
            resolved_path.relative_to(self.workspace)
        except ValueError:
            pass
        else:
            return False, "Executables located inside the DPN AI workspace are blocked"
        if executable not in ALLOWED_EXECUTABLES:
            return False, f"Executable '{executable}' is not allowed"
        return True, str(resolved_path)

    @staticmethod
    def _first_subcommand(args: list[str]) -> str:
        for part in args[1:]:
            if not part.startswith("-"):
                return part.lower()
        return ""

    def _validate_arguments(self, executable: str, args: list[str]) -> tuple[bool, str]:
        lowered = {part.lower() for part in args}
        if lowered.intersection(BLOCKED_TOKENS):
            return False, "Command contains a blocked system-management token"

        if executable in {"python", "python3", "py"} and any(part in {"-c", "-m"} for part in args[1:]):
            return False, "Inline Python and python -m are blocked. Write a script in the workspace first."
        if executable in {"node", "deno", "bun"} and any(part in {"-e", "--eval"} for part in args[1:]):
            return False, "Inline JavaScript execution is blocked. Write a script first."

        if executable in PACKAGE_MANAGER_BLOCKS:
            subcommand = self._first_subcommand(args)
            if subcommand in PACKAGE_MANAGER_BLOCKS[executable]:
                return False, f"Remote package operation '{executable} {subcommand}' is blocked by the safe runner"

        if executable == "git":
            normalized = [part.lower() for part in args[1:]]
            if "-c" in normalized or any(part.startswith("-c=") for part in normalized):
                return False, "Git runtime configuration overrides are blocked"
            subcommand = self._first_subcommand(args)
            if subcommand in BLOCKED_GIT_SUBCOMMANDS:
                return False, f"Git subcommand '{subcommand}' is blocked by the safe runner"
            joined = " ".join(normalized)
            if any(fragment in joined for fragment in BLOCKED_GIT_ARGUMENT_FRAGMENTS):
                return False, "Git command contains a blocked external-command or credential option"
            if subcommand == "reset" and "--hard" in normalized:
                return False, "git reset --hard is blocked by the safe runner"

        return True, ""

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

        executable_ok, resolved_or_error = self._resolve_executable(args[0], executable)
        if not executable_ok:
            return {"ok": False, "error": resolved_or_error}
        args[0] = resolved_or_error

        arguments_ok, reason = self._validate_arguments(executable, args)
        if not arguments_ok:
            return {"ok": False, "error": reason}

        workdir = self._resolve_cwd(cwd)
        timeout = max(5, min(timeout_seconds or self.timeout_seconds, 600))
        env = self._safe_environment()
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
