import hashlib

import pytest

from app.recovery_verification_v9 import (
    RecoveryFileEntry,
    RecoveryManifest,
    RecoveryVerificationError,
    validate_manifest,
    validate_rollback_order,
    verify_file_bytes,
)


def _entry(path: str, data: bytes) -> RecoveryFileEntry:
    return RecoveryFileEntry(path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def test_valid_manifest_and_file_bytes_pass():
    data = b"dpn-ai"
    entry = _entry("workspace/config.json", data)
    manifest = RecoveryManifest(schema_version=1, app_version="9.0.0", files=(entry,))
    result = validate_manifest(manifest)
    assert result.ok is True
    assert result.verified_files == 1
    assert result.total_bytes == len(data)
    assert verify_file_bytes(entry, data) is True


def test_manifest_rejects_path_traversal_and_absolute_paths():
    bad = RecoveryManifest(
        schema_version=1,
        app_version="9.0.0",
        files=(
            RecoveryFileEntry("../secret.txt", "0" * 64, 1),
            RecoveryFileEntry("/etc/passwd", "0" * 64, 1),
        ),
    )
    result = validate_manifest(bad)
    assert result.ok is False
    assert any("relative path" in error for error in result.errors)


def test_manifest_rejects_duplicate_paths_and_bad_hashes():
    manifest = RecoveryManifest(
        schema_version=1,
        app_version="9.0.0",
        files=(
            RecoveryFileEntry("a.txt", "0" * 64, 1),
            RecoveryFileEntry("a.txt", "1" * 64, 1),
            RecoveryFileEntry("b.txt", "NOT-A-HASH", 1),
        ),
    )
    result = validate_manifest(manifest)
    assert result.ok is False
    assert any("duplicate" in error for error in result.errors)
    assert any("SHA-256" in error for error in result.errors)


def test_manifest_enforces_schema_version_and_resource_limits():
    entry = RecoveryFileEntry("large.bin", "0" * 64, 50)
    manifest = RecoveryManifest(schema_version=2, app_version="9.0", files=(entry,))
    result = validate_manifest(manifest, max_total_bytes=10)
    assert result.ok is False
    assert "unsupported recovery manifest schema" in result.errors
    assert "invalid application version" in result.errors
    assert "recovery manifest exceeds total-size limit" in result.errors


def test_verify_file_bytes_fails_closed_on_size_or_digest_mismatch():
    data = b"abc"
    entry = _entry("file.bin", data)
    assert verify_file_bytes(entry, b"abcd") is False
    wrong = RecoveryFileEntry("file.bin", "0" * 64, len(data))
    assert verify_file_bytes(wrong, data) is False


def test_rollback_plan_must_reference_manifest_once():
    manifest = RecoveryManifest(
        schema_version=1,
        app_version="9.0.0",
        files=(_entry("a.txt", b"a"), _entry("b.txt", b"b")),
    )
    assert validate_rollback_order(["b.txt", "a.txt"], manifest) == ("b.txt", "a.txt")
    with pytest.raises(RecoveryVerificationError, match="not present"):
        validate_rollback_order(["c.txt"], manifest)
    with pytest.raises(RecoveryVerificationError, match="duplicated"):
        validate_rollback_order(["a.txt", "a.txt"], manifest)


def test_invalid_limits_and_empty_rollback_plan_are_rejected():
    manifest = RecoveryManifest(schema_version=1, app_version="9.0.0", files=(_entry("a.txt", b"a"),))
    with pytest.raises(RecoveryVerificationError, match="max_files"):
        validate_manifest(manifest, max_files=0)
    with pytest.raises(RecoveryVerificationError, match="max_file_bytes"):
        verify_file_bytes(manifest.files[0], b"a", max_file_bytes=0)
    with pytest.raises(RecoveryVerificationError, match="at least one"):
        validate_rollback_order([], manifest)
