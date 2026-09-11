#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

from desktop.updater import SignedUpdateManifest, verify_artifact, verify_manifest_signature

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Windows checksum manifest is missing or unsafe")
    expected: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw:
            continue
        parts = raw.split("  ", 1)
        if len(parts) != 2:
            raise ValueError(f"invalid checksum line {line_number}")
        digest, name = parts
        if SHA256_RE.fullmatch(digest) is None:
            raise ValueError(f"invalid SHA-256 on checksum line {line_number}")
        if not name or Path(name).name != name:
            raise ValueError(f"unsafe release filename on checksum line {line_number}")
        if name in expected:
            raise ValueError(f"duplicate checksum entry: {name}")
        expected[name] = digest
    if not expected:
        raise ValueError("Windows checksum manifest is empty")
    return expected


def verify_bundle(root: Path, *, version: str, channel: str, public_key_hex: str) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Windows release bundle directory is missing or unsafe")

    expected = parse_checksums(root / "WINDOWS_SHA256SUMS.txt")
    for name, digest in expected.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing or unsafe Windows release asset: {name}")
        if sha256_file(path) != digest:
            raise ValueError(f"Windows release asset checksum mismatch: {name}")

    required = {
        "installer-manifest.json",
        "source-build-manifest.json",
        "update-manifest.json",
    }
    if not required.issubset(expected):
        raise ValueError("Windows checksum manifest is incomplete")

    installers = [name for name in expected if name.startswith("DPN-AI-Setup-") and name.endswith(".exe")]
    if len(installers) != 1:
        raise ValueError("expected exactly one checksummed Windows installer")
    installer_name = installers[0]
    installer = root / installer_name

    installer_manifest = json.loads((root / "installer-manifest.json").read_text(encoding="utf-8-sig"))
    if not isinstance(installer_manifest, dict):
        raise ValueError("installer manifest must be a JSON object")
    if installer_manifest.get("version") != version:
        raise ValueError("installer manifest version mismatch")
    if installer_manifest.get("installer") != installer_name:
        raise ValueError("installer manifest filename mismatch")
    if installer_manifest.get("signing") != "signed-production-installer":
        raise ValueError("installer manifest does not record production signing")
    if installer_manifest.get("sha256") != sha256_file(installer):
        raise ValueError("installer manifest SHA-256 mismatch")
    thumbprint = str(installer_manifest.get("signer_thumbprint") or "").replace(" ", "").upper()
    if re.fullmatch(r"[A-F0-9]{40,64}", thumbprint) is None:
        raise ValueError("installer signer thumbprint is invalid")

    source_manifest = json.loads((root / "source-build-manifest.json").read_text(encoding="utf-8-sig"))
    if not isinstance(source_manifest, dict):
        raise ValueError("source build manifest must be a JSON object")
    if source_manifest.get("version") != version:
        raise ValueError("source build manifest version mismatch")
    if source_manifest.get("signing") != "signed-production-artifact":
        raise ValueError("source build manifest does not record production signing")
    if str(source_manifest.get("signer_thumbprint") or "").replace(" ", "").upper() != thumbprint:
        raise ValueError("source executable signer does not match installer signer")
    if source_manifest.get("update_trust_configured") is not True:
        raise ValueError("source build manifest does not record a packaged update trust root")
    trust_file_digest = str(source_manifest.get("update_trust_root_sha256") or "").strip().lower()
    if SHA256_RE.fullmatch(trust_file_digest) is None:
        raise ValueError("source build manifest update trust-root hash is invalid")

    public_hex = str(public_key_hex or "").strip().lower()
    if len(public_hex) != 64 or any(ch not in "0123456789abcdef" for ch in public_hex):
        raise ValueError("configured update public key is invalid")
    expected_key_fingerprint = hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()
    manifest_key_fingerprint = str(source_manifest.get("update_trust_public_key_sha256") or "").strip().lower()
    if not hmac.compare_digest(manifest_key_fingerprint, expected_key_fingerprint):
        raise ValueError("packaged update trust root does not match configured public key")
    update_manifest = SignedUpdateManifest.parse((root / "update-manifest.json").read_text(encoding="utf-8"))
    if not verify_manifest_signature(update_manifest, bytes.fromhex(public_hex)):
        raise ValueError("update manifest Ed25519 verification failed")
    verify_artifact(installer, update_manifest.artifact)
    if update_manifest.artifact.version != version:
        raise ValueError("update manifest version mismatch")
    if update_manifest.artifact.channel != channel:
        raise ValueError("update manifest channel mismatch")

    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a transferred DPN AI production Windows release bundle.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "beta"), required=True)
    args = parser.parse_args()

    expected = verify_bundle(
        args.root,
        version=args.version,
        channel=args.channel,
        public_key_hex=os.getenv("DPN_UPDATE_ED25519_PUBLIC_KEY_HEX", ""),
    )
    print(f"Verified {len(expected)} production Windows release assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
