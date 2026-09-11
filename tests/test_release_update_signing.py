import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from desktop.updater import SignedUpdateManifest, verify_artifact, verify_manifest_signature

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "sign_update_manifest.py"
SPEC = importlib.util.spec_from_file_location("dpn_sign_update_manifest", SCRIPT_PATH)
assert SPEC and SPEC.loader
SIGNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIGNER)


def _key_material() -> tuple[str, str, bytes]:
    private_key = Ed25519PrivateKey.generate()
    raw_private = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw_private).decode("ascii"), raw_public.hex(), raw_public


def _installer_fixture(tmp_path: Path, payload: bytes = b"signed-installer") -> tuple[Path, Path]:
    installer = tmp_path / "DPN-AI-Setup-10.0.1.exe"
    installer.write_bytes(payload)
    manifest = tmp_path / "installer-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "product": "DPN AI",
                "version": "10.0.1",
                "installer": installer.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "signing": "signed-production-installer",
            }
        ),
        encoding="utf-8",
    )
    return installer, manifest


def test_release_signer_creates_updater_compatible_manifest(tmp_path: Path):
    private_b64, public_hex, public_bytes = _key_material()
    installer, installer_manifest = _installer_fixture(tmp_path)

    payload = SIGNER.build_signed_update_manifest(
        installer=installer,
        installer_manifest_path=installer_manifest,
        version="10.0.1",
        channel="stable",
        private_key_b64=private_b64,
        expected_public_key_hex=public_hex,
    )

    parsed = SignedUpdateManifest.parse(json.dumps(payload))
    assert verify_manifest_signature(parsed, public_bytes) is True
    verify_artifact(installer, parsed.artifact)
    assert parsed.artifact.filename == installer.name
    assert parsed.artifact.version == "10.0.1"
    assert parsed.artifact.channel == "stable"
    assert payload["signing_key_fingerprint_sha256"] == hashlib.sha256(public_bytes).hexdigest()
    assert private_b64 not in json.dumps(payload)


def test_release_signer_rejects_unsigned_installer(tmp_path: Path):
    private_b64, public_hex, _ = _key_material()
    installer, installer_manifest = _installer_fixture(tmp_path)
    data = json.loads(installer_manifest.read_text(encoding="utf-8"))
    data["signing"] = "unsigned-development-installer"
    installer_manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Authenticode-signed"):
        SIGNER.build_signed_update_manifest(
            installer=installer,
            installer_manifest_path=installer_manifest,
            version="10.0.1",
            channel="stable",
            private_key_b64=private_b64,
            expected_public_key_hex=public_hex,
        )


def test_release_signer_rejects_public_private_key_mismatch(tmp_path: Path):
    private_b64, _, _ = _key_material()
    _, wrong_public_hex, _ = _key_material()
    installer, installer_manifest = _installer_fixture(tmp_path)

    with pytest.raises(ValueError, match="does not match"):
        SIGNER.build_signed_update_manifest(
            installer=installer,
            installer_manifest_path=installer_manifest,
            version="10.0.1",
            channel="stable",
            private_key_b64=private_b64,
            expected_public_key_hex=wrong_public_hex,
        )


def test_release_signer_rejects_malformed_private_key(tmp_path: Path):
    _, public_hex, _ = _key_material()
    installer, installer_manifest = _installer_fixture(tmp_path)

    with pytest.raises(ValueError, match="strict base64"):
        SIGNER.build_signed_update_manifest(
            installer=installer,
            installer_manifest_path=installer_manifest,
            version="10.0.1",
            channel="stable",
            private_key_b64="not base64 ***",
            expected_public_key_hex=public_hex,
        )


def test_release_signer_detects_installer_tampering(tmp_path: Path):
    private_b64, public_hex, _ = _key_material()
    installer, installer_manifest = _installer_fixture(tmp_path)
    installer.write_bytes(b"tampered-binary!")

    with pytest.raises(ValueError, match="SHA-256"):
        SIGNER.build_signed_update_manifest(
            installer=installer,
            installer_manifest_path=installer_manifest,
            version="10.0.1",
            channel="beta",
            private_key_b64=private_b64,
            expected_public_key_hex=public_hex,
        )


def test_release_signer_writes_atomically(tmp_path: Path):
    target = tmp_path / "nested" / "update-manifest.json"
    payload = {"artifact": {"version": "10.0.1"}, "signature": "00"}
    SIGNER.write_json_atomic(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []
