from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
LOCK_VERIFY = (ROOT / ".github/scripts/verify_release_lock.py").read_text(encoding="utf-8")


def _publication_job() -> str:
    return RELEASE.split("  release:\n", 1)[1]


def test_release_publication_uses_exact_production_dependency_closure():
    publication = _publication_job()
    assert 'python-version: "3.12.10"' in publication
    assert "requirements-release.lock" in publication
    assert "--no-deps" in publication
    assert "--only-binary=:all:" in publication
    assert "--verify-installed" in publication
    assert "python -m pip check" in publication
    assert "requirements-dev.txt" not in publication
    assert "pip install --upgrade pip" not in publication


def test_all_release_jobs_pin_same_exact_python_patch():
    assert RELEASE.count('python-version: "3.12.10"') == 3
    assert 'python-version: "3.12"' not in RELEASE
    assert "RELEASE_PYTHON = (3, 12, 10)" in LOCK_VERIFY
    assert "sys.version_info[:3] != RELEASE_PYTHON" in LOCK_VERIFY


def test_security_audit_toolchain_uses_exact_declared_closure_without_dependency_resolution():
    preflight = RELEASE.split("  security-preflight:\n", 1)[1].split("  windows-release-assets:\n", 1)[0]
    install_line = next(
        line.strip()
        for line in preflight.splitlines()
        if ".github/requirements-security.txt" in line and "pip install" in line
    )
    assert "--disable-pip-version-check" in install_line
    assert "--no-deps" in install_line
    assert "--only-binary=:all:" in install_line


def test_release_workflow_is_valid_yaml():
    parsed = yaml.safe_load(RELEASE)
    assert isinstance(parsed, dict)
    assert "jobs" in parsed
    assert {"security-preflight", "windows-release-assets", "release"}.issubset(parsed["jobs"])
