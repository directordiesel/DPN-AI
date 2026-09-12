import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import desktop.update_client as update_client_module
from desktop.update_client import (
    GitHubReleaseUpdateClient,
    UpdateClientError,
    UpdateTrustRoot,
    load_packaged_update_trust_root,
    verify_windows_authenticode,
)

ROOT = Path(__file__).resolve().parents[1]
WRITER_PATH = ROOT / ".github" / "scripts" / "write_update_trust_root.py"
WRITER_SPEC = importlib.util.spec_from_file_location("dpn_update_trust_writer", WRITER_PATH)
assert WRITER_SPEC and WRITER_SPEC.loader
WRITER = importlib.util.module_from_spec(WRITER_SPEC)
WRITER_SPEC.loader.exec_module(WRITER)
SIGNER_THUMBPRINT = "A" * 40


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, public.hex()


def _trust(private: Ed25519PrivateKey, public_hex: str) -> UpdateTrustRoot:
    del private
    raw = bytes.fromhex(public_hex)
    payload = {
        "schema_version": 1,
        "repository": "directordiesel/DPN-AI",
        "key_id": "release-ed25519-v1",
        "ed25519_public_key_hex": public_hex,
        "public_key_sha256": hashlib.sha256(raw).hexdigest(),
    }
    return UpdateTrustRoot.parse(json.dumps(payload))


def _signed_manifest(private: Ed25519PrivateKey, payload: bytes, *, version: str = "10.0.2") -> str:
    artifact = {
        "version": version,
        "channel": "stable",
        "filename": f"DPN-AI-Setup-{version}.exe",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "signer_thumbprint": SIGNER_THUMBPRINT,
    }
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signed = {
        "artifact": artifact,
        "key_id": "release-ed25519-v1",
        "repository": "directordiesel/DPN-AI",
        "schema_version": 3,
        "signing_key_fingerprint_sha256": hashlib.sha256(public).hexdigest(),
    }
    canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return json.dumps(
        {
            **signed,
            "signature_algorithm": "ed25519",
            "signature": private.sign(canonical).hex(),
        }
    )


def _release_payload(manifest_filename: str, installer_filename: str, *, version: str = "10.0.2") -> list[dict]:
    base = f"https://github.com/directordiesel/DPN-AI/releases/download/v{version}"
    return [
        {
            "draft": False,
            "prerelease": False,
            "tag_name": f"v{version}",
            "html_url": f"https://github.com/directordiesel/DPN-AI/releases/tag/v{version}",
            "assets": [
                {
                    "name": "update-manifest.json",
                    "browser_download_url": f"{base}/{manifest_filename}",
                },
                {
                    "name": installer_filename,
                    "browser_download_url": f"{base}/{installer_filename}",
                },
            ],
        }
    ]


@pytest.mark.asyncio
async def test_signed_release_discovery_and_streamed_download(tmp_path: Path):
    private, public_hex = _keypair()
    trust = _trust(private, public_hex)
    installer = b"verified-production-installer"
    manifest = _signed_manifest(private, installer)
    installer_name = "DPN-AI-Setup-10.0.2.exe"
    release_json = _release_payload("update-manifest.json", installer_name)

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == "api.github.com":
            return httpx.Response(200, json=release_json)
        if host == "github.com" and path.endswith("/update-manifest.json"):
            return httpx.Response(200, content=manifest.encode("utf-8"))
        if host == "github.com" and path.endswith(f"/{installer_name}"):
            return httpx.Response(
                302,
                headers={"Location": f"https://release-assets.githubusercontent.com/dpn/{installer_name}"},
            )
        if host == "release-assets.githubusercontent.com":
            return httpx.Response(
                200,
                content=installer,
                headers={"Content-Length": str(len(installer))},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    candidate = await client.check_for_update("10.0.1", channel="stable")
    assert candidate is not None
    assert candidate.manifest.artifact.version == "10.0.2"
    assert candidate.manifest.artifact.signer_thumbprint == SIGNER_THUMBPRINT

    result = await client.download_verified_installer(
        candidate,
        destination_dir=tmp_path / "updates",
        require_authenticode=False,
    )
    assert result.path.read_bytes() == installer
    assert result.sha256 == hashlib.sha256(installer).hexdigest()
    assert result.safe_summary()["verified"] is True
    assert not list((tmp_path / "updates").glob("*.part"))


@pytest.mark.asyncio
async def test_invalid_manifest_signature_fails_closed():
    private, public_hex = _keypair()
    wrong_private, _ = _keypair()
    trust = _trust(private, public_hex)
    installer = b"installer"
    manifest = _signed_manifest(wrong_private, installer)
    release_json = _release_payload("update-manifest.json", "DPN-AI-Setup-10.0.2.exe")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=release_json)
        return httpx.Response(200, content=manifest.encode("utf-8"))

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateClientError, match="signature verification failed"):
        await client.check_for_update("10.0.1")


@pytest.mark.asyncio
async def test_signed_manifest_cannot_redirect_installer_to_non_github_host():
    private, public_hex = _keypair()
    trust = _trust(private, public_hex)
    installer = b"installer"
    manifest = _signed_manifest(private, installer)
    release_json = _release_payload("update-manifest.json", "DPN-AI-Setup-10.0.2.exe")
    release_json[0]["assets"][1]["browser_download_url"] = "https://evil.example/update.exe"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=release_json)
        return httpx.Response(200, content=manifest.encode("utf-8"))

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateClientError, match="GitHub allowlist"):
        await client.check_for_update("10.0.1")


@pytest.mark.asyncio
async def test_tampered_installer_download_is_deleted(tmp_path: Path):
    private, public_hex = _keypair()
    trust = _trust(private, public_hex)
    trusted_installer = b"trusted-installer"
    tampered_installer = b"tampered-installer"
    manifest = _signed_manifest(private, trusted_installer)
    installer_name = "DPN-AI-Setup-10.0.2.exe"
    release_json = _release_payload("update-manifest.json", installer_name)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=release_json)
        if request.url.path.endswith("/update-manifest.json"):
            return httpx.Response(200, content=manifest.encode("utf-8"))
        return httpx.Response(200, content=tampered_installer)

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    candidate = await client.check_for_update("10.0.1")
    assert candidate is not None

    update_dir = tmp_path / "updates"
    with pytest.raises(UpdateClientError):
        await client.download_verified_installer(
            candidate,
            destination_dir=update_dir,
            require_authenticode=False,
        )
    assert not (update_dir / installer_name).exists()
    assert not list(update_dir.glob("*.part"))


def test_trust_root_writer_and_runtime_parser_agree(tmp_path: Path):
    _, public_hex = _keypair()
    payload = WRITER.build_trust_root(public_hex)
    target = tmp_path / "update-trust.json"
    WRITER.write_atomic(target, payload)

    parsed = load_packaged_update_trust_root(target)
    assert parsed.repository == "directordiesel/DPN-AI"
    assert parsed.public_key.hex() == public_hex
    assert parsed.public_key_sha256 == hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()


def test_missing_or_wrong_repository_trust_root_fails_closed(tmp_path: Path):
    with pytest.raises(UpdateClientError, match="does not contain"):
        load_packaged_update_trust_root(tmp_path / "missing.json")

    _, public_hex = _keypair()
    payload = WRITER.build_trust_root(public_hex)
    payload["repository"] = "attacker/repository"
    path = tmp_path / "update-trust.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(UpdateClientError, match="repository is not authorized"):
        load_packaged_update_trust_root(path)


def test_trust_root_writer_rejects_malformed_public_keys():
    for value in ("", "abc", "g" * 64, base64.b64encode(b"x" * 32).decode("ascii")):
        with pytest.raises(ValueError, match="64 hexadecimal"):
            WRITER.build_trust_root(value)


def test_windows_authenticode_requires_exact_expected_signer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"signed")
    monkeypatch.setattr(update_client_module.sys, "platform", "win32")

    def fake_run(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(returncode=0, stdout=f"{SIGNER_THUMBPRINT}\n")

    monkeypatch.setattr(update_client_module.subprocess, "run", fake_run)
    assert verify_windows_authenticode(installer, expected_thumbprint=SIGNER_THUMBPRINT) is True
    assert verify_windows_authenticode(installer, expected_thumbprint="B" * 40) is False


@pytest.mark.asyncio
async def test_production_update_rejects_tampered_signed_trust_metadata():
    private, public_hex = _keypair()
    trust = _trust(private, public_hex)
    installer = b"installer"
    raw = json.loads(_signed_manifest(private, installer))
    raw["repository"] = "attacker/repository"
    manifest = json.dumps(raw)
    release_json = _release_payload("update-manifest.json", "DPN-AI-Setup-10.0.2.exe")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=release_json)
        return httpx.Response(200, content=manifest.encode("utf-8"))

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateClientError, match="signature verification failed"):
        await client.check_for_update("10.0.1")


@pytest.mark.asyncio
async def test_production_update_rejects_legacy_artifact_only_manifest():
    private, public_hex = _keypair()
    trust = _trust(private, public_hex)
    artifact = {
        "version": "10.0.2",
        "channel": "stable",
        "filename": "DPN-AI-Setup-10.0.2.exe",
        "sha256": hashlib.sha256(b"installer").hexdigest(),
        "size": len(b"installer"),
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    legacy = json.dumps({
        "artifact": artifact,
        "signature_algorithm": "ed25519",
        "signature": private.sign(canonical).hex(),
    })
    release_json = _release_payload("update-manifest.json", artifact["filename"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=release_json)
        return httpx.Response(200, content=legacy.encode("utf-8"))

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateClientError, match="current signed trust schema"):
        await client.check_for_update("10.0.1")


@pytest.mark.asyncio
async def test_production_update_rejects_previous_schema_without_signed_windows_signer():
    private, public_hex = _keypair()
    trust = _trust(private, public_hex)
    installer = b"installer"
    artifact = {
        "version": "10.0.2",
        "channel": "stable",
        "filename": "DPN-AI-Setup-10.0.2.exe",
        "sha256": hashlib.sha256(installer).hexdigest(),
        "size": len(installer),
    }
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signed = {
        "artifact": artifact,
        "key_id": "release-ed25519-v1",
        "repository": "directordiesel/DPN-AI",
        "schema_version": 2,
        "signing_key_fingerprint_sha256": hashlib.sha256(public).hexdigest(),
    }
    canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    previous = json.dumps({**signed, "signature_algorithm": "ed25519", "signature": private.sign(canonical).hex()})
    release_json = _release_payload("update-manifest.json", artifact["filename"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=release_json)
        return httpx.Response(200, content=previous.encode("utf-8"))

    client = GitHubReleaseUpdateClient(trust, transport=httpx.MockTransport(handler))
    with pytest.raises(UpdateClientError, match="current signed trust schema"):
        await client.check_for_update("10.0.1")
