"""DPN AI v8 updater and rollback contracts.

The updater is intentionally fail-closed. It verifies signed release metadata,
artifact integrity, channel compatibility, and rollback availability before an
update can be staged for activation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_CHANNELS = {"stable", "beta", "dev"}


@dataclass(frozen=True)
class UpdateArtifact:
    version: str
    channel: str
    filename: str
    sha256: str
    size: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateArtifact":
        return cls(
            version=str(data.get("version", "")).strip(),
            channel=str(data.get("channel", "")).strip().lower(),
            filename=str(data.get("filename", "")).strip(),
            sha256=str(data.get("sha256", "")).strip().lower(),
            size=int(data.get("size", 0)),
        )

    def validate(self) -> None:
        if not self.version:
            raise ValueError("update version is required")
        if self.channel not in ALLOWED_CHANNELS:
            raise ValueError("invalid update channel")
        if not self.filename or Path(self.filename).name != self.filename:
            raise ValueError("update filename must be a basename")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("update sha256 must be a lowercase 64-character digest")
        if self.size <= 0:
            raise ValueError("update artifact size must be positive")


@dataclass(frozen=True)
class SignedUpdateManifest:
    artifact: UpdateArtifact
    signature: str

    @classmethod
    def parse(cls, raw: str) -> "SignedUpdateManifest":
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("artifact"), dict):
            raise ValueError("invalid update manifest shape")
        manifest = cls(
            artifact=UpdateArtifact.from_dict(data["artifact"]),
            signature=str(data.get("signature", "")).strip().lower(),
        )
        manifest.artifact.validate()
        if len(manifest.signature) != 64 or any(ch not in "0123456789abcdef" for ch in manifest.signature):
            raise ValueError("invalid update manifest signature")
        return manifest

    def canonical_artifact_json(self) -> bytes:
        payload = {
            "channel": self.artifact.channel,
            "filename": self.artifact.filename,
            "sha256": self.artifact.sha256,
            "size": self.artifact.size,
            "version": self.artifact.version,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_manifest_signature(manifest: SignedUpdateManifest, verification_key: bytes) -> bool:
    """Verify release metadata using an injected trusted key.

    This HMAC-backed contract keeps verification testable while the production
    signing provider/certificate implementation is added during release hardening.
    The verification key must be provisioned outside distributable source.
    """
    if not verification_key:
        return False
    expected = hmac.new(verification_key, manifest.canonical_artifact_json(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, manifest.signature)


def verify_artifact(path: Path, artifact: UpdateArtifact) -> None:
    artifact.validate()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.name != artifact.filename:
        raise ValueError("downloaded update filename does not match manifest")
    if path.stat().st_size != artifact.size:
        raise ValueError("downloaded update size does not match manifest")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, artifact.sha256):
        raise ValueError("downloaded update sha256 does not match manifest")


@dataclass(frozen=True)
class RollbackPlan:
    current_version: str
    target_version: str
    backup_path: Path

    def validate(self) -> None:
        if not self.current_version or not self.target_version:
            raise ValueError("rollback versions are required")
        if self.current_version == self.target_version:
            raise ValueError("rollback target must differ from current version")
        if not self.backup_path.is_file():
            raise ValueError("verified rollback backup is required")


def stage_update(
    manifest: SignedUpdateManifest,
    downloaded_artifact: Path,
    *,
    selected_channel: str,
    verification_key: bytes,
    rollback_backup: Path,
    current_version: str,
) -> RollbackPlan:
    selected_channel = selected_channel.strip().lower()
    if selected_channel not in ALLOWED_CHANNELS:
        raise ValueError("invalid selected update channel")
    if manifest.artifact.channel != selected_channel:
        raise ValueError("update channel does not match selected channel")
    if manifest.artifact.version == current_version:
        raise ValueError("update version matches current version")
    if not verify_manifest_signature(manifest, verification_key):
        raise ValueError("update manifest signature verification failed")
    verify_artifact(downloaded_artifact, manifest.artifact)

    plan = RollbackPlan(
        current_version=current_version,
        target_version=manifest.artifact.version,
        backup_path=rollback_backup,
    )
    plan.validate()
    return plan
