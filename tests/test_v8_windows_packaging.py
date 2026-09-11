import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = (ROOT / "packaging" / "windows" / "DPN-AI.spec").read_text(encoding="utf-8")
BUILD = (ROOT / "packaging" / "windows" / "build.ps1").read_text(encoding="utf-8")
SIGN = (ROOT / "packaging" / "windows" / "sign.ps1").read_text(encoding="utf-8")
BUILD_REQUIREMENTS = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")


def test_windows_build_toolchain_is_explicit_and_bounded():
    match = re.search(r"(?im)^pyinstaller>=(6\.\d+(?:\.\d+)?),<7$", BUILD_REQUIREMENTS)
    assert match is not None
    assert "-r requirements-dev.txt" in BUILD_REQUIREMENTS


def test_windows_package_is_gui_onedir_and_disables_upx():
    assert 'name="DPN-AI"' in SPEC
    assert "console=False" in SPEC
    assert "exclude_binaries=True" in SPEC
    assert "COLLECT(" in SPEC
    assert "upx=False" in SPEC


def test_package_contains_required_runtime_and_static_assets():
    assert 'ROOT / "VERSION"' in SPEC
    assert 'ROOT / "requirements.txt"' in SPEC
    assert 'ROOT / "app" / "static"' in SPEC
    assert 'ROOT / "desktop" / "launcher.py"' in SPEC
    assert 'collect_submodules("app")' in SPEC
    assert 'collect_submodules("desktop")' in SPEC


def test_packaging_does_not_bundle_known_secret_or_mutable_runtime_sources():
    lowered = SPEC.lower()
    for forbidden in ('.env"', "secrets.json", "dpn_ai.db", "workspace", "logs"):
        assert forbidden not in lowered


def test_build_fails_closed_and_runs_desktop_regressions_before_packaging():
    assert '$ErrorActionPreference = "Stop"' in BUILD
    assert "Set-StrictMode -Version Latest" in BUILD
    assert "tests/test_v8_desktop_platform.py" in BUILD
    assert "tests/test_v8_desktop_supervisor.py" in BUILD
    assert "tests/test_v8_desktop_service_api.py" in BUILD
    assert "tests/test_v8_windows_packaging.py" in BUILD
    assert "PyInstaller --noconfirm --clean" in BUILD


def test_development_builds_remain_explicitly_unsigned():
    assert '$SigningState = "unsigned-development-artifact"' in BUILD
    assert "development artifact remains unsigned" in BUILD
    assert "build-manifest.json" in BUILD


def test_release_build_can_require_verified_authenticode_signing():
    assert "[switch]$RequireSigned" in BUILD
    assert "Production signing is required but no CertificateThumbprint was supplied" in BUILD
    assert 'signed-production-artifact' in BUILD
    assert "sign.ps1" in BUILD
    assert "Get-AuthenticodeSignature" in SIGN
    assert "signtool.exe" in SIGN
    assert "/fd SHA256" in SIGN
    assert "/td SHA256" in SIGN
    assert "SignerCertificate.Thumbprint" in SIGN
    assert "Authenticode verification failed" in SIGN


def test_production_package_requires_and_verifies_public_update_trust_root():
    assert 'DPN_UPDATE_TRUST_FILE' in SPEC
    assert 'update-trust.json' in SPEC
    assert 'datas.append((str(trust_path), "desktop"))' in SPEC
    assert 'Production signing requires the packaged public update trust root.' in BUILD
    assert 'Get-ChildItem -Path (Join-Path $DistRoot "DPN-AI") -Filter "update-trust.json"' in BUILD
    assert 'Production package must contain exactly one update-trust.json file.' in BUILD
    assert 'Packaged update trust root does not match the configured production trust root.' in BUILD
    assert 'update_trust_configured = $UpdateTrustConfigured' in BUILD
    assert 'update_trust_root_sha256 = $UpdateTrustRootSha256' in BUILD
    assert 'update_trust_public_key_sha256 = $UpdateTrustPublicKeySha256' in BUILD
    assert 'Update trust root is not bound to the official DPN-AI repository.' in BUILD


def test_development_package_cannot_accidentally_ship_a_stale_update_trust_root():
    assert 'Development package unexpectedly contains an update trust root.' in BUILD
