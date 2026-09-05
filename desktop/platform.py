"""DPN AI v8 desktop platform lifecycle contracts.

This module is intentionally dependency-light so launcher, packaging, recovery, and
QA tooling can share one definition of the desktop runtime without duplicating the
AI itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


class DesktopMode(str, Enum):
    NORMAL = "normal"
    SAFE = "safe"
    DIAGNOSTIC = "diagnostic"


class ServiceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class DesktopPaths:
    install_root: Path
    data_root: Path
    log_root: Path
    backup_root: Path

    def validate(self) -> None:
        roots = (self.install_root, self.data_root, self.log_root, self.backup_root)
        if any(not isinstance(path, Path) for path in roots):
            raise TypeError("desktop paths must be pathlib.Path instances")
        if len({str(path.resolve()) for path in roots}) != len(roots):
            raise ValueError("desktop roots must be distinct")


@dataclass(frozen=True)
class ServiceEndpoint:
    host: str = "127.0.0.1"
    port: int = 8765
    tls: bool = False

    def validate(self, *, allow_remote: bool = False) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("service port must be between 1 and 65535")
        if not self.host.strip():
            raise ValueError("service host is required")
        loopback = self.host.strip().lower() in {"127.0.0.1", "localhost", "::1"}
        if not loopback and not allow_remote:
            raise ValueError("desktop service is loopback-only unless remote access is explicitly enabled")


@dataclass(frozen=True)
class DesktopRuntimePolicy:
    mode: DesktopMode = DesktopMode.NORMAL
    endpoint: ServiceEndpoint = field(default_factory=ServiceEndpoint)
    allow_remote: bool = False
    allow_cloud: bool = True
    require_authentication: bool = True
    require_audit: bool = True
    require_update_integrity: bool = True

    def validate(self) -> None:
        self.endpoint.validate(allow_remote=self.allow_remote)
        if not self.require_authentication:
            raise ValueError("desktop runtime may not disable authentication")
        if not self.require_audit:
            raise ValueError("desktop runtime may not disable audit logging")
        if not self.require_update_integrity:
            raise ValueError("desktop runtime may not disable update integrity verification")
        if self.allow_remote and not self.endpoint.tls:
            raise ValueError("remote desktop service access requires TLS")


@dataclass(frozen=True)
class PreflightResult:
    ready: bool
    checks: tuple[str, ...]
    blockers: tuple[str, ...] = ()


class DesktopPreflight:
    """Evaluate release/runtime invariants before the native shell starts."""

    REQUIRED_FILES = (
        "VERSION",
        "app/main.py",
        "requirements.txt",
    )

    def __init__(self, repository_root: Path, policy: DesktopRuntimePolicy) -> None:
        self.repository_root = repository_root.resolve()
        self.policy = policy

    def run(self, extra_required_files: Iterable[str] = ()) -> PreflightResult:
        checks: list[str] = []
        blockers: list[str] = []

        try:
            self.policy.validate()
            checks.append("runtime-policy")
        except (TypeError, ValueError) as exc:
            blockers.append(f"runtime-policy: {exc}")

        required = (*self.REQUIRED_FILES, *tuple(extra_required_files))
        for relative in required:
            target = (self.repository_root / relative).resolve()
            try:
                target.relative_to(self.repository_root)
            except ValueError:
                blockers.append(f"unsafe-required-path: {relative}")
                continue
            if target.is_file():
                checks.append(f"file:{relative}")
            else:
                blockers.append(f"missing-file: {relative}")

        return PreflightResult(
            ready=not blockers,
            checks=tuple(checks),
            blockers=tuple(blockers),
        )
