#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ALLOWED_CHANNELS = {"stable", "beta"}
HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_private_key(value: str) -> Ed25519PrivateKey:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("DPN_UPDATE_ED25519_PRIVATE_KEY_B64 is required")
    try:
        key_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Ed25519 private key must be strict base64") from exc
    if len(key_bytes) != 32:
        raise ValueError("Ed25519 private key must decode to exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(key_bytes)


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _validate_expected_public_key(private_key: Ed25519PrivateKey, expected_hex: str) -> bytes:
    expected = str(expected_hex or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("DPN_UPDATE_ED25519_PUBLIC_KEY_HEX must be exactly 64 hexadecimal characters")
    actual = _public_key_bytes(private_key)
    if not hmac.compare_digest(actual.hex(), expected):
        raise ValueError("Ed25519 private key does not match the configured public verification key")
    return actual


def _load_installer_manifest(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("installer manifest must not be a symlink")
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("installer manifest must be a JSON object")
    return data


def build_signed_update_manifest(
    *,
    installer: Path,
    installer_manifest_path: Path,
    version: str,
    channel: str,
    private_key_b64: str,
    expected_public_key_hex: str,
) -> dict[str, Any]:
    release_version = str(version or "").strip()
    release_channel = str(channel or "").strip().lower()
    if not release_version:
        raise ValueError("release version is required")
    if release_channel not in ALLOWED_CHANNELS:
        raise ValueError(f"release channel must be one of: {', '.join(sorted(ALLOWED_CHANNELS))}")
    if installer.is_symlink():
        raise ValueError("release installer must not be a symlink")
    if not installer.is_file():
        raise FileNotFoundError(installer)

    installer_manifest = _load_installer_manifest(installer_manifest_path)
    if installer_manifest.get("version") != release_version:
        raise ValueError("installer manifest version does not match release version")
    if installer_manifest.get("installer") != installer.name:
        raise ValueError("installer manifest filename does not match release installer")
    if installer_manifest.get("signing") != "signed-production-installer":
        raise ValueError("release installer must be Authenticode-signed for production")

    size = installer.stat().st_size
    if size <= 0:
        raise ValueError("release installer is empty")
    digest = sha256_file(installer)
    manifest_digest = str(installer_manifest.get("sha256") or "").strip().lower()
    if not hmac.compare_digest(digest, manifest_digest):
        raise ValueError("release installer SHA-256 does not match installer manifest")

    private_key = _load_private_key(private_key_b64)
    public_key = _validate_expected_public_key(private_key, expected_public_key_hex)

    artifact = {
        "version": release_version,
        "channel": release_channel,
        "filename": installer.name,
        "sha256": digest,
        "size": size,
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(canonical)
    try:
        private_key.public_key().verify(signature, canonical)
    except InvalidSignature as exc:
        raise ValueError("generated update signature failed self-verification") from exc

    return {
        "artifact": artifact,
        "signature_algorithm": "ed25519",
        "signature": signature.hex(),
        "signing_key_fingerprint_sha256": hashlib.sha256(public_key).hexdigest(),
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a production Ed25519-signed DPN AI update manifest.")
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--installer-manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=sorted(ALLOWED_CHANNELS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_signed_update_manifest(
        installer=args.installer,
        installer_manifest_path=args.installer_manifest,
        version=args.version,
        channel=args.channel,
        private_key_b64=os.getenv("DPN_UPDATE_ED25519_PRIVATE_KEY_B64", ""),
        expected_public_key_hex=os.getenv("DPN_UPDATE_ED25519_PUBLIC_KEY_HEX", ""),
    )
    write_json_atomic(args.output, payload)
    print(
        "Signed update manifest created for "
        f"{payload['artifact']['filename']} ({payload['artifact']['channel']}) "
        f"using key fingerprint {payload['signing_key_fingerprint_sha256'][:16]}..."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
