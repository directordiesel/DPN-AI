import hashlib
import hmac
import json
from pathlib import Path

import pytest

from desktop.updater import SignedUpdateManifest, stage_update, verify_artifact


def _manifest_for(payload: bytes, *, key: bytes, filename: str = "DPN-AI-8.0.0.exe", channel: str = "dev") -> str:
    artifact = {
        "version": "8.0.0-dev",
        "channel": channel,
        "filename": filename,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return json.dumps({"artifact": artifact, "signature": signature})


def test_valid_signed_update_requires_verified_rollback(tmp_path: Path):
    key = b"test-verification-key"
    payload = b"dpn-ai-build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    backup = tmp_path / "DPN-AI-7-backup.exe"
    backup.write_bytes(b"backup")

    manifest = SignedUpdateManifest.parse(_manifest_for(payload, key=key))
    plan = stage_update(
        manifest,
        update,
        selected_channel="dev",
        verification_key=key,
        rollback_backup=backup,
        current_version="7.0.0",
    )

    assert plan.current_version == "7.0.0"
    assert plan.target_version == "8.0.0-dev"
    assert plan.backup_path == backup


def test_wrong_signature_fails_closed(tmp_path: Path):
    payload = b"dpn-ai-build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    backup = tmp_path / "backup.exe"
    backup.write_bytes(b"backup")
    manifest = SignedUpdateManifest.parse(_manifest_for(payload, key=b"right-key"))

    with pytest.raises(ValueError, match="signature verification failed"):
        stage_update(
            manifest,
            update,
            selected_channel="dev",
            verification_key=b"wrong-key",
            rollback_backup=backup,
            current_version="7.0.0",
        )


def test_channel_mismatch_is_rejected(tmp_path: Path):
    payload = b"build"
    key = b"key"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    backup = tmp_path / "backup.exe"
    backup.write_bytes(b"backup")
    manifest = SignedUpdateManifest.parse(_manifest_for(payload, key=key, channel="beta"))

    with pytest.raises(ValueError, match="channel does not match"):
        stage_update(
            manifest,
            update,
            selected_channel="stable",
            verification_key=key,
            rollback_backup=backup,
            current_version="7.0.0",
        )


def test_tampered_artifact_is_rejected(tmp_path: Path):
    original = b"trusted-build"
    key = b"key"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(b"tampered-build")
    manifest = SignedUpdateManifest.parse(_manifest_for(original, key=key))

    with pytest.raises(ValueError):
        verify_artifact(update, manifest.artifact)


def test_missing_rollback_backup_blocks_staging(tmp_path: Path):
    key = b"key"
    payload = b"build"
    update = tmp_path / "DPN-AI-8.0.0.exe"
    update.write_bytes(payload)
    manifest = SignedUpdateManifest.parse(_manifest_for(payload, key=key))

    with pytest.raises(ValueError, match="rollback backup is required"):
        stage_update(
            manifest,
            update,
            selected_channel="dev",
            verification_key=key,
            rollback_backup=tmp_path / "missing-backup.exe",
            current_version="7.0.0",
        )


def test_manifest_rejects_path_traversal_filename():
    raw = json.loads(_manifest_for(b"build", key=b"key"))
    raw["artifact"]["filename"] = "../DPN-AI.exe"
    canonical = json.dumps(raw["artifact"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    raw["signature"] = hmac.new(b"key", canonical, hashlib.sha256).hexdigest()

    with pytest.raises(ValueError, match="basename"):
        SignedUpdateManifest.parse(json.dumps(raw))
