import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.updater import SignedUpdateManifest, stage_update, verify_artifact


def _keypair() -> tuple[Ed25519PrivateKey, bytes]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, public_key


def _manifest_for(
    payload: bytes,
    *,
    private_key: Ed25519PrivateKey,
    filename: str = "DPN-AI-8.0.0.exe",
    channel: str = "dev",
) -> str:
    artifact = {
        "version": "8.0.0-dev",
        "channel": channel,
        "filename": filename,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(canonical).hex()
    return json.dumps({
        "artifact": artifact,
        "signature_algorithm": "ed25519",
        "signature": signature,
    })


def test_valid_signed_update_requires_verified_rollback(tmp_path: Path):
    private_key, public_key = _keypair()
    payload = b"dpn-ai-build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    backup = tmp_path / "DPN-AI-7-backup.exe"
    backup.write_bytes(b"backup")

    manifest = SignedUpdateManifest.parse(_manifest_for(payload, private_key=private_key))
    plan = stage_update(
        manifest,
        update,
        selected_channel="dev",
        verification_key=public_key,
        rollback_backup=backup,
        current_version="7.0.0",
    )

    assert plan.current_version == "7.0.0"
    assert plan.target_version == "8.0.0-dev"
    assert plan.backup_path == backup


def test_wrong_signature_fails_closed(tmp_path: Path):
    signing_key, _ = _keypair()
    _, wrong_public_key = _keypair()
    payload = b"dpn-ai-build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    backup = tmp_path / "backup.exe"
    backup.write_bytes(b"backup")
    manifest = SignedUpdateManifest.parse(_manifest_for(payload, private_key=signing_key))

    with pytest.raises(ValueError, match="signature verification failed"):
        stage_update(
            manifest,
            update,
            selected_channel="dev",
            verification_key=wrong_public_key,
            rollback_backup=backup,
            current_version="7.0.0",
        )


def test_channel_mismatch_is_rejected(tmp_path: Path):
    private_key, public_key = _keypair()
    payload = b"build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    backup = tmp_path / "backup.exe"
    backup.write_bytes(b"backup")
    manifest = SignedUpdateManifest.parse(
        _manifest_for(payload, private_key=private_key, channel="beta")
    )

    with pytest.raises(ValueError, match="channel does not match"):
        stage_update(
            manifest,
            update,
            selected_channel="stable",
            verification_key=public_key,
            rollback_backup=backup,
            current_version="7.0.0",
        )


def test_tampered_artifact_is_rejected(tmp_path: Path):
    private_key, _ = _keypair()
    original = b"trusted-build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(b"tampered-build")
    manifest = SignedUpdateManifest.parse(_manifest_for(original, private_key=private_key))

    with pytest.raises(ValueError):
        verify_artifact(update, manifest.artifact)


def test_missing_rollback_backup_blocks_staging(tmp_path: Path):
    private_key, public_key = _keypair()
    payload = b"build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    manifest = SignedUpdateManifest.parse(_manifest_for(payload, private_key=private_key))

    with pytest.raises(ValueError, match="rollback backup is required"):
        stage_update(
            manifest,
            update,
            selected_channel="dev",
            verification_key=public_key,
            rollback_backup=tmp_path / "missing-backup.exe",
            current_version="7.0.0",
        )


def test_manifest_rejects_path_traversal_filename():
    private_key, _ = _keypair()
    raw = json.loads(_manifest_for(b"build", private_key=private_key))
    raw["artifact"]["filename"] = "../DPN-AI.exe"
    canonical = json.dumps(raw["artifact"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    raw["signature"] = private_key.sign(canonical).hex()

    with pytest.raises(ValueError, match="basename"):
        SignedUpdateManifest.parse(json.dumps(raw))


def test_manifest_rejects_legacy_or_unknown_signature_algorithms():
    private_key, _ = _keypair()
    raw = json.loads(_manifest_for(b"build", private_key=private_key))
    raw["signature_algorithm"] = "hmac-sha256"

    with pytest.raises(ValueError, match="Ed25519"):
        SignedUpdateManifest.parse(json.dumps(raw))


def test_public_verification_key_is_not_a_signing_secret():
    private_key, public_key = _keypair()
    payload = b"build"
    manifest = SignedUpdateManifest.parse(_manifest_for(payload, private_key=private_key))
    assert len(public_key) == 32
    assert manifest.signature_algorithm == "ed25519"
