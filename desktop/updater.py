"""DPN AI updater and rollback security contracts.

Production update manifests use an Ed25519-signed schema that binds the
artifact to the official repository, signing-key identity, verification-key
fingerprint, and expected Windows Authenticode signer. Legacy manifests remain
parseable for development compatibility, but production callers must explicitly
require the current trust binding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_CHANNELS = {"stable", "beta", "dev"}
HASH_CHUNK_BYTES = 1024 * 1024
UPDATE_MANIFEST_SCHEMA_VERSION = 4
UPDATE_REPOSITORY = "directordiesel/DPN-AI"
UPDATE_KEY_ID = "release-ed25519-v1"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_THUMBPRINT_RE = re.compile(r"^[A-F0-9]{40,64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class UpdateArtifact:
    version: str
    channel: str
    filename: str
    sha256: str
    size: int
    signer_thumbprint: str = ""
    source_commit_sha: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateArtifact":
        return cls(
            version=str(data.get("version", "")).strip(),
            channel=str(data.get("channel", "")).strip().lower(),
            filename=str(data.get("filename", "")).strip(),
            sha256=str(data.get("sha256", "")).strip().lower(),
            size=int(data.get("size", 0)),
            signer_thumbprint=str(data.get("signer_thumbprint", "")).replace(" ", "").strip().upper(),
            source_commit_sha=str(data.get("source_commit_sha", "")).strip().lower(),
        )

    def validate(
        self,
        *,
        require_signer_thumbprint: bool = False,
        require_source_commit_sha: bool = False,
    ) -> None:
        if not self.version:
            raise ValueError("update version is required")
        if self.channel not in ALLOWED_CHANNELS:
            raise ValueError("invalid update channel")
        if not self.filename or Path(self.filename).name != self.filename:
            raise ValueError("update filename must be a basename")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("update sha256 must be a lowercase 64-character digest")
        if self.size <= 0:
            raise ValueError("update artifact size must be positive")
        if self.signer_thumbprint and _THUMBPRINT_RE.fullmatch(self.signer_thumbprint) is None:
            raise ValueError("update Authenticode signer thumbprint is invalid")
        if require_signer_thumbprint and not self.signer_thumbprint:
            raise ValueError("production update manifest must bind the Authenticode signer thumbprint")
        if self.source_commit_sha and _GIT_COMMIT_RE.fullmatch(self.source_commit_sha) is None:
            raise ValueError("update source commit SHA is invalid")
        if require_source_commit_sha and not self.source_commit_sha:
            raise ValueError("production update manifest must bind the source commit SHA")

    def canonical_dict(self) -> dict[str, Any]:
        payload = {
            "channel": self.channel,
            "filename": self.filename,
            "sha256": self.sha256,
            "size": self.size,
            "version": self.version,
        }
        if self.signer_thumbprint:
            payload["signer_thumbprint"] = self.signer_thumbprint
        if self.source_commit_sha:
            payload["source_commit_sha"] = self.source_commit_sha
        return payload


@dataclass(frozen=True)
class SignedUpdateManifest:
    artifact: UpdateArtifact
    signature: str
    signature_algorithm: str = "ed25519"
    schema_version: int = 1
    repository: str = ""
    key_id: str = ""
    signing_key_fingerprint_sha256: str = ""

    @classmethod
    def parse(cls, raw: str) -> "SignedUpdateManifest":
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("artifact"), dict):
            raise ValueError("invalid update manifest shape")
        algorithm = str(data.get("signature_algorithm", "")).strip().lower()
        if algorithm != "ed25519":
            raise ValueError("update manifest must use Ed25519 signatures")
        try:
            schema_version = int(data.get("schema_version", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("update manifest schema version is invalid") from exc
        if schema_version not in {1, 2, 3, UPDATE_MANIFEST_SCHEMA_VERSION}:
            raise ValueError("unsupported update manifest schema version")

        repository = str(data.get("repository") or "").strip()
        key_id = str(data.get("key_id") or "").strip()
        fingerprint = str(data.get("signing_key_fingerprint_sha256") or "").strip().lower()
        if schema_version >= 2:
            if not repository or "/" not in repository:
                raise ValueError("update manifest repository binding is invalid")
            if _KEY_ID_RE.fullmatch(key_id) is None:
                raise ValueError("update manifest key id is invalid")
            if _SHA256_RE.fullmatch(fingerprint) is None:
                raise ValueError("update manifest signing-key fingerprint is invalid")
        elif repository or key_id or fingerprint:
            raise ValueError("legacy update manifest must not contain unsigned trust metadata")

        manifest = cls(
            artifact=UpdateArtifact.from_dict(data["artifact"]),
            signature=str(data.get("signature", "")).strip().lower(),
            signature_algorithm=algorithm,
            schema_version=schema_version,
            repository=repository,
            key_id=key_id,
            signing_key_fingerprint_sha256=fingerprint,
        )
        manifest.artifact.validate(
            require_signer_thumbprint=schema_version >= 3,
            require_source_commit_sha=schema_version >= UPDATE_MANIFEST_SCHEMA_VERSION,
        )
        if schema_version < 3 and manifest.artifact.signer_thumbprint:
            raise ValueError("legacy update manifest must not contain Authenticode signer metadata")
        if schema_version < UPDATE_MANIFEST_SCHEMA_VERSION and manifest.artifact.source_commit_sha:
            raise ValueError("legacy update manifest must not contain source-commit metadata")
        if len(manifest.signature) != 128 or any(ch not in "0123456789abcdef" for ch in manifest.signature):
            raise ValueError("invalid Ed25519 update manifest signature")
        return manifest

    def canonical_signed_json(self) -> bytes:
        if self.schema_version == 1:
            payload: dict[str, Any] = self.artifact.canonical_dict()
        else:
            payload = {
                "artifact": self.artifact.canonical_dict(),
                "key_id": self.key_id,
                "repository": self.repository,
                "schema_version": self.schema_version,
                "signing_key_fingerprint_sha256": self.signing_key_fingerprint_sha256,
            }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def canonical_artifact_json(self) -> bytes:
        """Backward-compatible alias used by older development tests."""
        return self.canonical_signed_json()


def verify_manifest_signature(manifest: SignedUpdateManifest, verification_key: bytes) -> bool:
    """Verify the signed update manifest with a 32-byte Ed25519 public key."""
    if manifest.signature_algorithm != "ed25519" or len(verification_key) != 32:
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(verification_key)
        signature = bytes.fromhex(manifest.signature)
        public_key.verify(signature, manifest.canonical_signed_json())
        return True
    except (InvalidSignature, ValueError):
        return False


def validate_manifest_trust_binding(
    manifest: SignedUpdateManifest,
    *,
    repository: str,
    key_id: str,
    public_key_sha256: str,
) -> None:
    """Require the current production schema and its signed trust identity."""
    if manifest.schema_version != UPDATE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("production update manifest must use the current signed trust schema")
    manifest.artifact.validate(require_signer_thumbprint=True, require_source_commit_sha=True)
    if not hmac.compare_digest(manifest.repository, str(repository)):
        raise ValueError("update manifest repository binding mismatch")
    if not hmac.compare_digest(manifest.key_id, str(key_id)):
        raise ValueError("update manifest key-id binding mismatch")
    expected_fingerprint = str(public_key_sha256 or "").strip().lower()
    if _SHA256_RE.fullmatch(expected_fingerprint) is None:
        raise ValueError("expected update verification-key fingerprint is invalid")
    if not hmac.compare_digest(manifest.signing_key_fingerprint_sha256, expected_fingerprint):
        raise ValueError("update manifest verification-key fingerprint mismatch")


def verify_artifact(path: Path, artifact: UpdateArtifact) -> None:
    artifact.validate()
    if path.is_symlink():
        raise ValueError("downloaded update must not be a symlink")
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.name != artifact.filename:
        raise ValueError("downloaded update filename does not match manifest")
    if path.stat().st_size != artifact.size:
        raise ValueError("downloaded update size does not match manifest")
    digest = _sha256_file(path)
    if not hmac.compare_digest(digest, artifact.sha256):
        raise ValueError("downloaded update sha256 does not match manifest")


@dataclass(frozen=True)
class RollbackPlan:
    current_version: str
    target_version: str
    backup_path: Path
    backup_sha256: str
    backup_size: int

    def validate(self) -> None:
        if not self.current_version or not self.target_version:
            raise ValueError("rollback versions are required")
        if self.current_version == self.target_version:
            raise ValueError("rollback target must differ from current version")
        if self.backup_path.is_symlink():
            raise ValueError("rollback backup must not be a symlink")
        if not self.backup_path.is_file():
            raise ValueError("verified rollback backup is required")
        if self.backup_size <= 0 or self.backup_path.stat().st_size != self.backup_size:
            raise ValueError("rollback backup size verification failed")
        if _SHA256_RE.fullmatch(self.backup_sha256) is None:
            raise ValueError("rollback backup sha256 is invalid")
        actual = _sha256_file(self.backup_path)
        if not hmac.compare_digest(actual, self.backup_sha256):
            raise ValueError("rollback backup sha256 verification failed")


def stage_update(
    manifest: SignedUpdateManifest,
    downloaded_artifact: Path,
    *,
    selected_channel: str,
    verification_key: bytes,
    rollback_backup: Path,
    rollback_sha256: str,
    rollback_size: int,
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
        backup_sha256=str(rollback_sha256).strip().lower(),
        backup_size=int(rollback_size),
    )
    plan.validate()
    return plan


__all__ = [
    "ALLOWED_CHANNELS",
    "RollbackPlan",
    "SignedUpdateManifest",
    "UPDATE_KEY_ID",
    "UPDATE_MANIFEST_SCHEMA_VERSION",
    "UPDATE_REPOSITORY",
    "UpdateArtifact",
    "stage_update",
    "validate_manifest_trust_binding",
    "verify_artifact",
    "verify_manifest_signature",
]
