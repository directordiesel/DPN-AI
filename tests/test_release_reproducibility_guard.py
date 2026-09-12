from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def _publication_job() -> str:
    return RELEASE.split("  release:\n", 1)[1]


def test_release_publication_uses_exact_production_dependency_closure():
    publication = _publication_job()
    assert 'python-version: "3.12"' in publication
    assert "requirements-release.lock" in publication
    assert "--no-deps" in publication
    assert "--only-binary=:all:" in publication
    assert "--verify-installed" in publication
    assert "python -m pip check" in publication
    assert "requirements-dev.txt" not in publication
    assert "pip install --upgrade pip" not in publication


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
