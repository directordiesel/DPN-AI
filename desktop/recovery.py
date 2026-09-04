"""Crash recovery, safe-mode escalation, diagnostics, and backup evidence for DPN AI v8.

This module deliberately does not implement an independent restore path. Recovery
backups are evidence-preserving artifacts; restoration remains owned by DPN AI's
validated snapshot/restore subsystem so integrity policy is not duplicated.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


class RecoveryStateError(RuntimeError):
    """Raised when persisted recovery evidence is malformed or unsafe."""


@dataclass(frozen=True)
class RecoveryPolicy:
    repository_root: Path
    state_directory: str = ".dpn-desktop-recovery"
    crash_threshold: int = 3
    crash_window_seconds: int = 600
    backup_retention: int = 5
    diagnostic_event_limit: int = 25

    def validate(self) -> None:
        if self.crash_threshold < 1 or self.crash_threshold > 10:
            raise ValueError("crash_threshold must be between 1 and 10")
        if self.crash_window_seconds < 30 or self.crash_window_seconds > 86400:
            raise ValueError("crash_window_seconds must be between 30 and 86400")
        if self.backup_retention < 1 or self.backup_retention > 20:
            raise ValueError("backup_retention must be between 1 and 20")
        if self.diagnostic_event_limit < 1 or self.diagnostic_event_limit > 200:
            raise ValueError("diagnostic_event_limit must be between 1 and 200")
        if not self.repository_root:
            raise ValueError("repository_root is required")


@dataclass(frozen=True)
class CrashEvent:
    timestamp: float
    exit_code: int | None
    error: str


class CrashRecoveryController:
    def __init__(self, policy: RecoveryPolicy) -> None:
        policy.validate()
        self.policy = policy
        self.root = policy.repository_root.resolve()
        self.state_dir = self._resolve_inside_root(policy.state_directory)
        self.journal_path = self.state_dir / "crashes.jsonl"
        self.state_path = self.state_dir / "recovery-state.json"
        self.backup_dir = self.state_dir / "backups"
        self.diagnostic_dir = self.state_dir / "diagnostics"

    def _resolve_inside_root(self, relative: str | Path) -> Path:
        candidate = (self.root / Path(relative)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise RecoveryStateError(f"recovery path escapes repository root: {relative}") from exc
        return candidate

    def _ensure_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize_error(error: str) -> str:
        text = " ".join(str(error).replace("\x00", "").split())
        return text[:2000] or "unknown failure"

    def record_crash(
        self,
        *,
        exit_code: int | None,
        error: str,
        timestamp: float | None = None,
    ) -> CrashEvent:
        self._ensure_directories()
        event = CrashEvent(
            timestamp=float(time.time() if timestamp is None else timestamp),
            exit_code=exit_code,
            error=self._sanitize_error(error),
        )
        payload = json.dumps(asdict(event), sort_keys=True, separators=(",", ":"))
        with self.journal_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def load_crashes(self) -> list[CrashEvent]:
        if not self.journal_path.exists():
            return []
        events: list[CrashEvent] = []
        for line_number, raw in enumerate(self.journal_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
                timestamp = float(payload["timestamp"])
                exit_code = payload.get("exit_code")
                if exit_code is not None:
                    exit_code = int(exit_code)
                error = self._sanitize_error(str(payload["error"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RecoveryStateError(f"invalid crash journal entry at line {line_number}") from exc
            events.append(CrashEvent(timestamp=timestamp, exit_code=exit_code, error=error))
        return events

    def recent_crashes(self, *, now: float | None = None) -> list[CrashEvent]:
        current = float(time.time() if now is None else now)
        lower_bound = current - self.policy.crash_window_seconds
        return [event for event in self.load_crashes() if lower_bound <= event.timestamp <= current]

    def should_enter_safe_mode(self, *, now: float | None = None) -> bool:
        try:
            return len(self.recent_crashes(now=now)) >= self.policy.crash_threshold
        except RecoveryStateError:
            # Corrupt recovery evidence is itself a reason to fail closed into safe mode.
            return True

    def write_recovery_state(self, *, safe_mode: bool, reason: str) -> Path:
        self._ensure_directories()
        payload = {
            "safe_mode": bool(safe_mode),
            "reason": self._sanitize_error(reason),
            "updated_at": time.time(),
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)
        return self.state_path

    def create_backup(self, paths: Iterable[str | Path], *, timestamp: int | None = None) -> tuple[Path, Path]:
        self._ensure_directories()
        selected: list[tuple[Path, Path]] = []
        for item in paths:
            source = self._resolve_inside_root(item)
            if not source.is_file():
                raise FileNotFoundError(f"backup source does not exist: {item}")
            selected.append((source, source.relative_to(self.root)))
        if not selected:
            raise ValueError("at least one backup source is required")

        stamp = int(time.time() if timestamp is None else timestamp)
        archive = self.backup_dir / f"recovery-{stamp}.zip"
        temporary = archive.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for source, relative in sorted(selected, key=lambda pair: pair[1].as_posix()):
                bundle.write(source, arcname=relative.as_posix())
        os.replace(temporary, archive)

        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum = archive.with_suffix(archive.suffix + ".sha256")
        checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
        self._enforce_backup_retention()
        return archive, checksum

    def _enforce_backup_retention(self) -> None:
        archives = sorted(self.backup_dir.glob("recovery-*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        for archive in archives[self.policy.backup_retention :]:
            checksum = archive.with_suffix(archive.suffix + ".sha256")
            archive.unlink(missing_ok=True)
            checksum.unlink(missing_ok=True)

    def write_diagnostics(self, *, state: str, pid: int | None, last_error: str | None) -> Path:
        self._ensure_directories()
        try:
            crashes = self.load_crashes()[-self.policy.diagnostic_event_limit :]
            journal_error = None
        except RecoveryStateError as exc:
            crashes = []
            journal_error = str(exc)

        version_path = self.root / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else "unknown"
        payload = {
            "version": version,
            "state": str(state),
            "pid": pid,
            "last_error": self._sanitize_error(last_error or "") or None,
            "safe_mode_recommended": self.should_enter_safe_mode(),
            "journal_error": journal_error,
            "recent_crashes": [asdict(event) for event in crashes],
            "generated_at": time.time(),
        }
        target = self.diagnostic_dir / f"diagnostics-{int(payload['generated_at'])}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, target)
        return target
