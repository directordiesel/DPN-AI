"""DPN AI v8 Windows desktop integration.

The module is dependency-light and intentionally keeps Windows integration per-user.
It does not mutate the machine unless an explicit install/uninstall method is called.
All registry writes are bounded to HKCU and all command payloads are derived from a
validated executable path.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


APP_ID = "DPNTechnology.DPNAI"
STARTUP_VALUE_NAME = "DPN AI"
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
CLASSES_ROOT = r"HKCU\Software\Classes"


@dataclass(frozen=True)
class WindowsIntegrationPolicy:
    startup_enabled: bool = False
    context_menu_enabled: bool = False
    open_with_enabled: bool = False
    notifications_enabled: bool = True


@dataclass(frozen=True)
class WindowsIntegrationResult:
    changed: bool
    actions: tuple[str, ...]


class WindowsIntegrationError(RuntimeError):
    pass


def _validate_executable(executable: Path) -> Path:
    path = executable.expanduser().resolve()
    if path.suffix.lower() != ".exe":
        raise ValueError("Windows integration requires a .exe executable")
    if '"' in str(path):
        raise ValueError("executable path may not contain a quote character")
    return path


def _quoted(path: Path) -> str:
    return f'"{path}"'


class WindowsIntegrationController:
    def __init__(
        self,
        executable: Path,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.executable = _validate_executable(executable)
        self._runner = runner

    def _require_windows(self) -> None:
        if os.name != "nt":
            raise WindowsIntegrationError("Windows integration is only available on Windows")

    def _reg(self, *args: str) -> None:
        self._require_windows()
        completed = self._runner(
            ["reg.exe", *args],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "registry operation failed").strip()
            raise WindowsIntegrationError(detail[:1000])

    def install_startup(self) -> WindowsIntegrationResult:
        command = f'{_quoted(self.executable)} --startup'
        self._reg("ADD", RUN_KEY, "/v", STARTUP_VALUE_NAME, "/t", "REG_SZ", "/d", command, "/f")
        return WindowsIntegrationResult(True, ("startup-installed",))

    def remove_startup(self) -> WindowsIntegrationResult:
        self._reg("DELETE", RUN_KEY, "/v", STARTUP_VALUE_NAME, "/f")
        return WindowsIntegrationResult(True, ("startup-removed",))

    def install_context_menu(self) -> WindowsIntegrationResult:
        root = rf"{CLASSES_ROOT}\*\shell\DPNAI"
        command_key = rf"{root}\command"
        command = f'{_quoted(self.executable)} --open-file "%1"'
        self._reg("ADD", root, "/ve", "/t", "REG_SZ", "/d", "Open with DPN AI", "/f")
        self._reg("ADD", root, "/v", "Icon", "/t", "REG_SZ", "/d", str(self.executable), "/f")
        self._reg("ADD", command_key, "/ve", "/t", "REG_SZ", "/d", command, "/f")
        return WindowsIntegrationResult(True, ("context-menu-installed",))

    def remove_context_menu(self) -> WindowsIntegrationResult:
        self._reg("DELETE", rf"{CLASSES_ROOT}\*\shell\DPNAI", "/f")
        return WindowsIntegrationResult(True, ("context-menu-removed",))

    def install_open_with(self) -> WindowsIntegrationResult:
        application_root = rf"{CLASSES_ROOT}\Applications\{self.executable.name}"
        command_key = rf"{application_root}\shell\open\command"
        command = f'{_quoted(self.executable)} --open-file "%1"'
        self._reg("ADD", application_root, "/v", "FriendlyAppName", "/t", "REG_SZ", "/d", "DPN AI", "/f")
        self._reg("ADD", command_key, "/ve", "/t", "REG_SZ", "/d", command, "/f")
        return WindowsIntegrationResult(True, ("open-with-installed",))

    def remove_open_with(self) -> WindowsIntegrationResult:
        self._reg("DELETE", rf"{CLASSES_ROOT}\Applications\{self.executable.name}", "/f")
        return WindowsIntegrationResult(True, ("open-with-removed",))

    def apply(self, policy: WindowsIntegrationPolicy) -> WindowsIntegrationResult:
        actions: list[str] = []
        operations = (
            (policy.startup_enabled, self.install_startup, self.remove_startup),
            (policy.context_menu_enabled, self.install_context_menu, self.remove_context_menu),
            (policy.open_with_enabled, self.install_open_with, self.remove_open_with),
        )
        for enabled, install, remove in operations:
            result = install() if enabled else remove()
            actions.extend(result.actions)
        return WindowsIntegrationResult(bool(actions), tuple(actions))


@dataclass
class TrayState:
    service_online: bool = False
    pending_approvals: int = 0
    active_missions: int = 0
    update_available: bool = False

    def tooltip(self) -> str:
        state = "Online" if self.service_online else "Offline"
        return (
            f"DPN AI — {state} | Missions {max(0, self.active_missions)} | "
            f"Approvals {max(0, self.pending_approvals)}"
        )

    def notification_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.pending_approvals > 0:
            reasons.append("approval-required")
        if self.update_available:
            reasons.append("update-available")
        return tuple(reasons)
