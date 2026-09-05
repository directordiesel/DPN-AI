from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS = (ROOT / "packaging" / "windows" / "DPN-AI.iss").read_text(encoding="utf-8")
BUILD = (ROOT / "packaging" / "windows" / "build-installer.ps1").read_text(encoding="utf-8")
SIGN = (ROOT / "packaging" / "windows" / "sign.ps1").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "windows-desktop-package.yml").read_text(encoding="utf-8")


def test_installer_has_stable_upgrade_identity_and_version_injection():
    assert '#define AppId "{{9E6D64D2-47F6-4D62-B73D-7D9AB758F31A}"' in ISS
    assert "#ifndef AppVersion" in ISS
    assert "AppVersion={#AppVersion}" in ISS
    assert "UsePreviousAppDir=yes" in ISS


def test_installer_defaults_to_per_user_location_without_environment_mutation():
    assert r"DefaultDirName={localappdata}\Programs\DPN Technology\DPN AI" in ISS
    assert "PrivilegesRequired=lowest" in ISS
    assert "ChangesEnvironment=no" in ISS
    assert "ChangesAssociations=no" in ISS


def test_uninstall_does_not_delete_user_data_locations():
    section = ISS.split("[UninstallDelete]", 1)[1].split("[Code]", 1)[0]
    directives = "\n".join(line.strip() for line in section.splitlines() if line.strip().lower().startswith("type:"))
    forbidden = (
        "workspace",
        "projects",
        "memory",
        "database",
        ".db",
        "backup",
        "settings",
        "appdata",
        "userprofile",
    )
    for token in forbidden:
        assert token not in directives.lower()
    assert r'Type: filesandordirs; Name: "{app}\__pycache__"' in directives


def test_installer_build_verifies_package_integrity_before_compilation():
    assert "Get-FileHash -Algorithm SHA256 $PackageExe" in BUILD
    assert "does not match build-manifest.json" in BUILD
    assert "$PackageManifest.version -ne $Version" in BUILD
    assert "Invoke-Checked $Compiler" in BUILD
    assert BUILD.index("Get-FileHash -Algorithm SHA256 $PackageExe") < BUILD.index("Invoke-Checked $Compiler")


def test_installer_build_never_implicitly_installs_tooling_on_trusted_runner():
    assert "Refusing to download or install build tools implicitly on the trusted runner" in BUILD
    assert "Invoke-WebRequest" not in BUILD
    assert "choco install" not in BUILD.lower()
    assert "winget install" not in BUILD.lower()


def test_installer_manifest_records_upgrade_data_and_signing_policy():
    for required in (
        'upgrade_behavior = "same-app-id-in-place-upgrade-repair"',
        'uninstall_data_policy = "preserve-user-data-outside-install-directory"',
        '$SigningState = "unsigned-development-installer"',
        "source_executable_sha256 = $ActualPackageHash",
        "source_executable_signing = $PackageManifest.signing",
    ):
        assert required in BUILD


def test_release_installer_requires_signed_source_and_verified_signature():
    assert "[switch]$RequireSigned" in BUILD
    assert "Production installer build requires the packaged executable to be signed first" in BUILD
    assert 'signed-production-installer' in BUILD
    assert "sign.ps1" in BUILD
    assert "Get-AuthenticodeSignature" in SIGN
    assert "SignerCertificate.Thumbprint" in SIGN


def test_trusted_packaging_workflow_keeps_pr_binary_execution_disabled():
    assert "if: github.event_name != 'pull_request'" in WORKFLOW
    assert "runs-on: [self-hosted, Windows, X64]" in WORKFLOW
    assert 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File ".\\packaging\\windows\\build-installer.ps1" -Python "%PYTHON_EXE%"' in WORKFLOW
    assert "shell: cmd" in WORKFLOW
    assert r".github\scripts\resolve_windows_python.cmd" in WORKFLOW
    assert "preserve-user-data-outside-install-directory" in WORKFLOW
