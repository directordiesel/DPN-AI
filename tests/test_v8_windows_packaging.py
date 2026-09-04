from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = (ROOT / "packaging" / "windows" / "DPN-AI.spec").read_text(encoding="utf-8")
BUILD = (ROOT / "packaging" / "windows" / "build.ps1").read_text(encoding="utf-8")
BUILD_REQUIREMENTS = (ROOT / "requirements-build.txt").read_text(encoding="utf-8")


def test_windows_build_toolchain_is_explicit_and_bounded():
    assert "pyinstaller>=6.16,<7" in BUILD_REQUIREMENTS.lower()
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
    assert "tests/test_v8_desktop_service.py" in BUILD
    assert "tests/test_v8_windows_packaging.py" in BUILD
    assert "PyInstaller --noconfirm --clean" in BUILD


def test_build_generates_sha256_manifest_and_does_not_claim_signature():
    assert "Get-FileHash -Algorithm SHA256" in BUILD
    assert 'signing = "unsigned-development-artifact"' in BUILD
    assert "build-manifest.json" in BUILD
    assert "NOTE: development artifacts remain unsigned" in BUILD
