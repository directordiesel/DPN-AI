"""DPN AI v8 updater and rollback contracts.

The updater is intentionally fail-closed. It verifies signed release metadata,
artifact integrity, channel compatibility, and rollback availability before an
update can be staged for activation.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
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
    signature_algorithm: str = "ed25519"

    @classmethod
    def parse(cls, raw: str) -> "SignedUpdateManifest":
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("artifact"), dict):
            raise ValueError("invalid update manifest shape")
        algorithm = str(data.get("signature_algorithm", "")).strip().lower()
        if algorithm != "ed25519":
            raise ValueError("update manifest must use Ed25519 signatures")
        manifest = cls(
            artifact=UpdateArtifact.from_dict(data["artifact"]),
            signature=str(data.get("signature", "")).strip().lower(),
            signature_algorithm=algorithm,
        )
        manifest.artifact.validate()
        if len(manifest.signature) != 128 or any(ch not in "0123456789abcdef" for ch in manifest.signature):
            raise ValueError("invalid Ed25519 update manifest signature")
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
    """Verify release metadata with an Ed25519 public key.

    The application requires only the 32-byte public verification key. The
    private signing key must remain outside distributable source, installers,
    runtime state, and update metadata.
    """
    if manifest.signature_algorithm != "ed25519" or len(verification_key) != 32:
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(verification_key)
        signature = bytes.fromhex(manifest.signature)
        public_key.verify(signature, manifest.canonical_artifact_json())
        return True
    except (InvalidSignature, ValueError):
        return False


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
