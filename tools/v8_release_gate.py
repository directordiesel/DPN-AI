from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "8.0.0"

REQUIRED_FILES = (
    "desktop/platform.py",
    "desktop/supervisor.py",
    "desktop/service.py",
    "desktop/updater.py",
    "desktop/windows_integration.py",
    "desktop/recovery.py",
    "desktop/resources.py",
    "packaging/windows/DPN-AI.spec",
    "packaging/windows/DPN-AI.iss",
    "packaging/windows/sign.ps1",
    ".github/workflows/v8-validation.yml",
    ".github/workflows/windows-desktop-package.yml",
    "tests/test_v8_desktop_platform.py",
    "tests/test_v8_desktop_supervisor.py",
    "tests/test_v8_desktop_service_api.py",
    "tests/test_v8_updater.py",
    "tests/test_v8_windows_installer.py",
    "tests/test_v8_windows_integration.py",
    "tests/test_v8_windows_packaging.py",
    "tests/test_v8_recovery.py",
    "tests/test_v8_resources.py",
)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def evaluate() -> list[str]:
    blockers: list[str] = []

    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            blockers.append(f"missing required v8 file: {relative}")

    version = text("VERSION").strip()
    if version != EXPECTED_VERSION:
        blockers.append(f"VERSION must be {EXPECTED_VERSION} for stable v8 promotion (current: {version})")

    readme = text("README.md")
    if EXPECTED_VERSION not in readme:
        blockers.append("README.md does not identify v8.0.0 release readiness")

    changelog = text("CHANGELOG.md")
    if EXPECTED_VERSION not in changelog:
        blockers.append("CHANGELOG.md does not contain v8.0.0 release notes")

    package_workflow = text(".github/workflows/windows-desktop-package.yml")
    if "github.event_name != 'pull_request'" not in package_workflow:
        blockers.append("Windows packaging is not restricted away from pull-request execution")
    if "runs-on: [self-hosted, Windows, X64]" not in package_workflow:
        blockers.append("Windows packaging is not pinned to the trusted Windows self-hosted runner class")

    release_workflow = text(".github/workflows/release.yml")
    trigger_block = release_workflow.split("permissions:", 1)[0]
    if "workflow_dispatch:" not in trigger_block:
        blockers.append("stable release workflow is not manual workflow_dispatch")
    if "\n  push:" in trigger_block:
        blockers.append("stable release workflow still permits push-triggered publication")
    if "refs/heads/main" not in release_workflow:
        blockers.append("stable release workflow is not restricted to main")

    sign_script = text("packaging/windows/sign.ps1")
    package_build = text("packaging/windows/build.ps1")
    installer_build = text("packaging/windows/build-installer.ps1")
    signing_contract = (
        "signtool.exe" in sign_script
        and "Get-AuthenticodeSignature" in sign_script
        and "SignerCertificate.Thumbprint" in sign_script
        and "[switch]$RequireSigned" in package_build
        and "signed-production-artifact" in package_build
        and "[switch]$RequireSigned" in installer_build
        and "signed-production-installer" in installer_build
    )
    if not signing_contract:
        blockers.append("production Authenticode signing integration is incomplete")

    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(description="DPN AI v8 strict release-readiness gate")
    parser.add_argument("--report", action="store_true", help="print blockers without returning a failing exit code")
    args = parser.parse_args()

    blockers = evaluate()
    if blockers:
        print("DPN AI v8 release blockers:")
        for blocker in blockers:
            print(f"- {blocker}")
        return 0 if args.report else 1

    print("DPN AI v8 source release gate passed. Signed release artifacts must still be produced and verified by the trusted release workflow before publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
