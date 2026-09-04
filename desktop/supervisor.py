"""DPN AI v8 native desktop service supervisor.

The supervisor owns lifecycle state for the local DPN AI service. It is designed to
be callable from a packaged Windows GUI executable (pythonw/PyInstaller no-console)
without changing the underlying AI runtime.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from desktop.platform import DesktopMode, DesktopPreflight, DesktopRuntimePolicy, ServiceState


@dataclass(frozen=True)
class SupervisorConfig:
    repository_root: Path
    python_executable: str = sys.executable
    module: str = "app.main:app"
    startup_timeout_seconds: float = 30.0
    graceful_shutdown_seconds: float = 8.0
    max_restart_attempts: int = 2

    def validate(self) -> None:
        if not self.repository_root:
            raise ValueError("repository_root is required")
        if not str(self.python_executable).strip():
            raise ValueError("python_executable is required")
        if not str(self.module).strip():
            raise ValueError("module is required")
        if self.startup_timeout_seconds <= 0:
            raise ValueError("startup timeout must be positive")
        if self.graceful_shutdown_seconds <= 0:
            raise ValueError("graceful shutdown timeout must be positive")
        if not 0 <= self.max_restart_attempts <= 5:
            raise ValueError("max_restart_attempts must be between 0 and 5")


@dataclass
class SupervisorSnapshot:
    state: ServiceState = ServiceState.STOPPED
    pid: int | None = None
    restarts: int = 0
    last_exit_code: int | None = None
    last_error: str | None = None


class DesktopServiceSupervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        policy: DesktopRuntimePolicy,
        *,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        health_check: Callable[[], bool] | None = None,
    ) -> None:
        config.validate()
        policy.validate()
        self.config = config
        self.policy = policy
        self._process_factory = process_factory
        self._health_check = health_check or (lambda: True)
        self._process: subprocess.Popen | None = None
        self.snapshot = SupervisorSnapshot()

    def build_command(self) -> list[str]:
        endpoint = self.policy.endpoint
        return [
            self.config.python_executable,
            "-m",
            "uvicorn",
            self.config.module,
            "--host",
            endpoint.host,
            "--port",
            str(endpoint.port),
            "--no-access-log",
        ]

    def build_environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["DPN_DESKTOP_MODE"] = self.policy.mode.value
        env["DPN_DESKTOP_SUPERVISED"] = "1"
        env["DPN_NO_BROWSER"] = "1"
        env["DPN_DESKTOP_ALLOW_REMOTE"] = "1" if self.policy.allow_remote else "0"
        if not self.policy.allow_cloud:
            env["DPN_LOCAL_ONLY"] = "1"
        return env

    def preflight(self) -> None:
        result = DesktopPreflight(self.config.repository_root, self.policy).run()
        if not result.ready:
            self.snapshot.state = ServiceState.FAILED
            self.snapshot.last_error = "; ".join(result.blockers)
            raise RuntimeError(self.snapshot.last_error)

    def start(self) -> SupervisorSnapshot:
        if self._process and self._process.poll() is None:
            return self.snapshot

        self.preflight()
        self.snapshot.state = ServiceState.STARTING
        self.snapshot.last_error = None

        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        self._process = self._process_factory(
            self.build_command(),
            cwd=str(self.config.repository_root),
            env=self.build_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self.snapshot.pid = getattr(self._process, "pid", None)

        deadline = time.monotonic() + self.config.startup_timeout_seconds
        while time.monotonic() < deadline:
            code = self._process.poll()
            if code is not None:
                self.snapshot.last_exit_code = code
                self.snapshot.state = ServiceState.FAILED
                self.snapshot.last_error = f"service exited during startup with code {code}"
                raise RuntimeError(self.snapshot.last_error)
            if self._health_check():
                self.snapshot.state = ServiceState.HEALTHY
                return self.snapshot
            time.sleep(0.1)

        self.snapshot.state = ServiceState.DEGRADED
        self.snapshot.last_error = "service health check timed out"
        raise TimeoutError(self.snapshot.last_error)

    def stop(self) -> SupervisorSnapshot:
        process = self._process
        if not process or process.poll() is not None:
            self.snapshot.state = ServiceState.STOPPED
            self.snapshot.pid = None
            return self.snapshot

        self.snapshot.state = ServiceState.STOPPING
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
            process.wait(timeout=self.config.graceful_shutdown_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

        self.snapshot.last_exit_code = process.poll()
        self.snapshot.pid = None
        self.snapshot.state = ServiceState.STOPPED
        self._process = None
        return self.snapshot

    def ensure_healthy(self) -> SupervisorSnapshot:
        process = self._process
        if process and process.poll() is None and self._health_check():
            self.snapshot.state = ServiceState.HEALTHY
            return self.snapshot

        if process is not None and process.poll() is not None:
            self.snapshot.last_exit_code = process.poll()

        if self.snapshot.restarts >= self.config.max_restart_attempts:
            self.snapshot.state = ServiceState.FAILED
            self.snapshot.last_error = "restart budget exhausted"
            return self.snapshot

        self.snapshot.restarts += 1
        self._process = None
        try:
            return self.start()
        except Exception as exc:  # supervisor must retain evidence for diagnostics
            self.snapshot.state = ServiceState.FAILED
            self.snapshot.last_error = str(exc)
            return self.snapshot

    def enter_safe_mode(self) -> "DesktopServiceSupervisor":
        safe_policy = DesktopRuntimePolicy(
            mode=DesktopMode.SAFE,
            endpoint=self.policy.endpoint,
            allow_remote=False,
            allow_cloud=False,
            require_authentication=True,
            require_audit=True,
            require_update_integrity=True,
        )
        return DesktopServiceSupervisor(
            self.config,
            safe_policy,
            process_factory=self._process_factory,
            health_check=self._health_check,
        )
