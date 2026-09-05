from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


class RecoveryVerificationError(ValueError):
    """Raised when recovery metadata fails deterministic safety validation."""


@dataclass(frozen=True)
class RecoveryFileEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class RecoveryManifest:
    schema_version: int
    app_version: str
    files: tuple[RecoveryFileEntry, ...]


@dataclass(frozen=True)
class RecoveryVerificationResult:
    ok: bool
    verified_files: int
    total_bytes: int
    errors: tuple[str, ...]


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def _safe_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or len(raw) > 1024 or "\x00" in raw:
        raise RecoveryVerificationError("recovery path is empty or invalid")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RecoveryVerificationError("recovery path must be a normalized relative path")
    if ":" in path.parts[0]:
        raise RecoveryVerificationError("recovery path must not contain a drive prefix")
    return path.as_posix()


def validate_manifest(manifest: RecoveryManifest, *, max_files: int = 100_000, max_total_bytes: int = 100 * 1024**3) -> RecoveryVerificationResult:
    errors: list[str] = []
    if isinstance(manifest.schema_version, bool) or manifest.schema_version != 1:
        errors.append("unsupported recovery manifest schema")
    if not _VERSION_RE.fullmatch(str(manifest.app_version or "")):
        errors.append("invalid application version")
    if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= 1_000_000:
        raise RecoveryVerificationError("max_files must be between 1 and 1000000")
    if isinstance(max_total_bytes, bool) or not isinstance(max_total_bytes, int) or max_total_bytes < 1:
        raise RecoveryVerificationError("max_total_bytes must be a positive integer")
    if len(manifest.files) > max_files:
        errors.append("recovery manifest exceeds file-count limit")

    seen: set[str] = set()
    total_bytes = 0
    verified = 0
    for entry in manifest.files:
        try:
            path = _safe_relative_path(entry.path)
        except RecoveryVerificationError as exc:
            errors.append(str(exc))
            continue
        if path in seen:
            errors.append(f"duplicate recovery path: {path}")
            continue
        seen.add(path)
        if not _SHA256_RE.fullmatch(str(entry.sha256 or "")):
            errors.append(f"invalid SHA-256 digest: {path}")
            continue
        if isinstance(entry.size, bool) or not isinstance(entry.size, int) or entry.size < 0:
            errors.append(f"invalid file size: {path}")
            continue
        total_bytes += entry.size
        if total_bytes > max_total_bytes:
            errors.append("recovery manifest exceeds total-size limit")
            break
        verified += 1

    return RecoveryVerificationResult(
        ok=not errors,
        verified_files=verified,
        total_bytes=total_bytes,
        errors=tuple(errors),
    )


def verify_file_bytes(entry: RecoveryFileEntry, data: bytes, *, max_file_bytes: int = 8 * 1024**3) -> bool:
    _safe_relative_path(entry.path)
    if not _SHA256_RE.fullmatch(str(entry.sha256 or "")):
        raise RecoveryVerificationError("recovery file digest is invalid")
    if isinstance(entry.size, bool) or not isinstance(entry.size, int) or entry.size < 0:
        raise RecoveryVerificationError("recovery file size is invalid")
    if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes < 1:
        raise RecoveryVerificationError("max_file_bytes must be a positive integer")
    if entry.size > max_file_bytes or len(data) > max_file_bytes:
        return False
    if len(data) != entry.size:
        return False
    return hashlib.sha256(data).hexdigest() == entry.sha256


def validate_rollback_order(paths: Iterable[str], manifest: RecoveryManifest) -> tuple[str, ...]:
    known = {_safe_relative_path(entry.path) for entry in manifest.files}
    ordered: list[str] = []
    seen: set[str] = set()
    for value in paths:
        path = _safe_relative_path(value)
        if path not in known:
            raise RecoveryVerificationError(f"rollback path is not present in recovery manifest: {path}")
        if path in seen:
            raise RecoveryVerificationError(f"rollback path is duplicated: {path}")
        seen.add(path)
        ordered.append(path)
    if not ordered:
        raise RecoveryVerificationError("rollback plan must contain at least one file")
    return tuple(ordered)


__all__ = [
    "RecoveryFileEntry",
    "RecoveryManifest",
    "RecoveryVerificationError",
    "RecoveryVerificationResult",
    "validate_manifest",
    "validate_rollback_order",
    "verify_file_bytes",
]
