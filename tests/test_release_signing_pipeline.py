import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
BUILDER = (ROOT / "packaging/windows/build-release-assets.ps1").read_text(encoding="utf-8")

SIGNER_SPEC = importlib.util.spec_from_file_location(
    "dpn_release_signer",
    ROOT / ".github/scripts/sign_update_manifest.py",
)
assert SIGNER_SPEC and SIGNER_SPEC.loader
SIGNER = importlib.util.module_from_spec(SIGNER_SPEC)
SIGNER_SPEC.loader.exec_module(SIGNER)

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "dpn_release_bundle_verify",
    ROOT / ".github/scripts/verify_windows_release_bundle.py",
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


def _key_material() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw_private).decode("ascii"), raw_public.hex()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_release_requires_signed_windows_assets_before_publication():
    assert "security-preflight:" in RELEASE
    assert "needs: security-preflight" in RELEASE
    assert "windows-release-assets:" in RELEASE
    assert "needs: windows-release-assets" in RELEASE
    assert RELEASE.index("security-preflight:") < RELEASE.index("windows-release-assets:") < RELEASE.index("  release:")
    assert "Build verified signed production Windows assets" in RELEASE
    assert "packaging\\windows\\build-release-assets.ps1" in RELEASE
    assert "Verify transferred production Windows bundle" in RELEASE
    assert ".github/scripts/verify_windows_release_bundle.py" in RELEASE


def test_release_signing_material_is_external_and_fail_closed():
    for secret in (
        "DPN_WINDOWS_SIGNING_PFX_B64",
        "DPN_WINDOWS_SIGNING_PFX_PASSWORD",
        "DPN_UPDATE_ED25519_PRIVATE_KEY_B64",
        "DPN_UPDATE_ED25519_PUBLIC_KEY_HEX",
    ):
        assert f"secrets.{secret}" in RELEASE
        assert f'"{secret}"' in BUILDER
    assert "Required production signing secret is not configured" in BUILDER
    assert "BEGIN PRIVATE KEY" not in RELEASE + BUILDER


def test_release_pipeline_uses_immutable_actions_and_least_privilege():
    assert "permissions:\n  contents: read" in RELEASE
    preflight = RELEASE.split("  security-preflight:", 1)[1].split("  windows-release-assets:", 1)[0]
    windows = RELEASE.split("  windows-release-assets:", 1)[1].split("  release:", 1)[0]
    publication = RELEASE.split("  release:", 1)[1]
    assert "id-token: write" not in preflight
    assert "attestations: write" not in preflight
    assert "contents: read" in windows
    assert "id-token: write" in windows
    assert "attestations: write" in windows
    assert "contents: write" in publication
    assert "id-token: write" in publication
    assert "attestations: write" in publication
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in RELEASE
    assert "actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131" in RELEASE
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in RELEASE
    assert "@v4" not in RELEASE
    assert "@v7" not in RELEASE


def test_production_builder_imports_nonexportable_cert_and_always_cleans_it():
    assert "Import-PfxCertificate" in BUILDER
    assert "-Exportable:$false" in BUILDER
    assert "finally {" in BUILDER
    assert 'Remove-Item -LiteralPath $PfxPath' in BUILDER
    assert "foreach ($ImportedCertificate in $ImportedCertificates)" in BUILDER
    assert 'Cert:\\CurrentUser\\My\\$ImportedThumbprint' in BUILDER
    assert "Remove-Item -LiteralPath $ImportedPath" in BUILDER
    assert "[Array]::Clear($PfxBytes, 0, $PfxBytes.Length)" in BUILDER
    assert "$Password.Dispose()" in BUILDER
    assert "https://timestamp.digicert.com" in BUILDER
    assert "Production timestamp URL must use HTTPS" in BUILDER


def test_production_builder_requires_dual_signing_and_verification():
    assert '"build.ps1"' in BUILDER
    assert '"build-installer.ps1"' in BUILDER
    assert "RequireSigned = $true" in BUILDER
    assert "sign_update_manifest.py" in BUILDER
    assert "Get-AuthenticodeSignature -FilePath $InstallerPath" in BUILDER
    assert "verify_manifest_signature" in BUILDER
    assert "verify_artifact" in BUILDER
    assert "WINDOWS_SHA256SUMS.txt" in BUILDER


def test_linux_bundle_verifier_accepts_valid_signed_bundle(tmp_path: Path):
    private_b64, public_hex = _key_material()
    version = "10.0.1"
    installer = tmp_path / f"DPN-AI-Setup-{version}.exe"
    installer.write_bytes(b"production-installer")
    thumbprint = "A" * 40

    installer_manifest = {
        "version": version,
        "installer": installer.name,
        "sha256": _sha256(installer),
        "signing": "signed-production-installer",
        "signer_thumbprint": thumbprint,
    }
    (tmp_path / "installer-manifest.json").write_text(json.dumps(installer_manifest), encoding="utf-8")
    (tmp_path / "source-build-manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "sha256": "0" * 64,
                "signing": "signed-production-artifact",
                "signer_thumbprint": thumbprint,
            }
        ),
        encoding="utf-8",
    )

    update_payload = SIGNER.build_signed_update_manifest(
        installer=installer,
        installer_manifest_path=tmp_path / "installer-manifest.json",
        version=version,
        channel="stable",
        private_key_b64=private_b64,
        expected_public_key_hex=public_hex,
    )
    (tmp_path / "update-manifest.json").write_text(json.dumps(update_payload), encoding="utf-8")

    names = (
        installer.name,
        "installer-manifest.json",
        "source-build-manifest.json",
        "update-manifest.json",
    )
    (tmp_path / "WINDOWS_SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(tmp_path / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )

    verified = VERIFY.verify_bundle(
        tmp_path,
        version=version,
        channel="stable",
        public_key_hex=public_hex,
    )
    assert set(verified) == set(names)


def test_linux_bundle_verifier_rejects_transfer_tampering(tmp_path: Path):
    private_b64, public_hex = _key_material()
    version = "10.0.1"
    installer = tmp_path / f"DPN-AI-Setup-{version}.exe"
    installer.write_bytes(b"production-installer")
    thumbprint = "B" * 40
    manifest_path = tmp_path / "installer-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": version,
                "installer": installer.name,
                "sha256": _sha256(installer),
                "signing": "signed-production-installer",
                "signer_thumbprint": thumbprint,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "source-build-manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "signing": "signed-production-artifact",
                "signer_thumbprint": thumbprint,
            }
        ),
        encoding="utf-8",
    )
    update_payload = SIGNER.build_signed_update_manifest(
        installer=installer,
        installer_manifest_path=manifest_path,
        version=version,
        channel="stable",
        private_key_b64=private_b64,
        expected_public_key_hex=public_hex,
    )
    (tmp_path / "update-manifest.json").write_text(json.dumps(update_payload), encoding="utf-8")

    names = (
        installer.name,
        "installer-manifest.json",
        "source-build-manifest.json",
        "update-manifest.json",
    )
    (tmp_path / "WINDOWS_SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(tmp_path / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )
    installer.write_bytes(b"tampered-installer!")

    with pytest.raises(ValueError, match="checksum mismatch"):
        VERIFY.verify_bundle(
            tmp_path,
            version=version,
            channel="stable",
            public_key_hex=public_hex,
        )


def test_release_security_preflight_audits_all_python_surfaces():
    assert "Run repository and source security guards" in RELEASE
    assert "python tools/dpn_security_gate.py --github" in RELEASE
    assert ".github/requirements-security.txt" in RELEASE
    assert "python -m pip_audit -r" in RELEASE
    for requirement in (
        "requirements.txt",
        "requirements-build.txt",
        "requirements-browser.txt",
        "requirements-desktop.txt",
        "requirements-voice.txt",
    ):
        assert requirement in RELEASE


def test_release_provenance_attests_at_actual_build_boundaries():
    windows = RELEASE.split("  windows-release-assets:", 1)[1].split("  release:", 1)[0]
    publication = RELEASE.split("  release:", 1)[1]

    assert "Attest production Windows release bundle" in windows
    for subject in (
        "dist/installer/DPN-AI-Setup-*.exe",
        "dist/installer/installer-manifest.json",
        "dist/installer/source-build-manifest.json",
        "dist/installer/update-manifest.json",
        "dist/installer/WINDOWS_SHA256SUMS.txt",
    ):
        assert subject in windows
    assert windows.index("Build verified signed production Windows assets") < windows.index("Attest production Windows release bundle")
    assert windows.index("Attest production Windows release bundle") < windows.index("Upload verified production Windows assets")

    assert "Attest release source archive" in publication
    assert 'subject-path: "${{ env.ARTIFACT_BASENAME }}-${{ env.VERSION }}-source.zip"' in publication
    assert publication.index("Build source archive and checksums") < publication.index("Attest release source archive")
    assert publication.index("Attest release source archive") < publication.index("Create GitHub Release")
