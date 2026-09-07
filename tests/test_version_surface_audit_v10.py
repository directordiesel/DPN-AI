from pathlib import Path

import pytest

from app.production_release_v10 import ProductionReleaseError
from app.version_surface_audit_v10 import collect_active_version_values, require_promoted_repository_versions


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(root: Path, *, version: str = "10.0.0", readme_tag: str = "v10.0.0") -> None:
    _write(root, "VERSION", f"{version}\n")
    _write(root, "app/main.py", f'APP_VERSION = "{version}"\n')
    _write(root, "README.md", f"<strong>Stable release:</strong> {readme_tag} &nbsp;•&nbsp;\n")
    _write(
        root,
        "app/static/sw.js",
        f"const CACHE = 'dpn-ai-v{version}-ui-shell';\n",
    )
    _write(root, "app/static/index.html", f'<link rel="stylesheet" href="/styles.css?v={version}" />\n')
    _write(root, "app/static/app.js", f"navigator.serviceWorker.register('/sw.js?v={version}');\n")
    _write(root, "ROADMAP.md", f"> Current stable baseline: **v{version}**\n")


def test_repository_backed_surface_audit_accepts_exact_promoted_state(tmp_path: Path) -> None:
    _repo(tmp_path)
    values = collect_active_version_values(tmp_path)
    assert values["VERSION"] == "10.0.0"
    assert values["readme_stable_identity"] == "v10.0.0"
    assert require_promoted_repository_versions(tmp_path) == values


def test_repository_backed_surface_audit_detects_stale_active_version(tmp_path: Path) -> None:
    _repo(tmp_path, version="9.0.0", readme_tag="v9.0.0")
    with pytest.raises(ProductionReleaseError):
        require_promoted_repository_versions(tmp_path)


def test_repository_backed_surface_audit_rejects_ambiguous_runtime_identity(tmp_path: Path) -> None:
    _repo(tmp_path)
    _write(tmp_path, "app/main.py", 'APP_VERSION = "10.0.0"\nAPP_VERSION = "10.0.0"\n')
    with pytest.raises(ProductionReleaseError, match="exactly one recognized identity"):
        collect_active_version_values(tmp_path)


def test_repository_backed_surface_audit_rejects_noncanonical_version_file(tmp_path: Path) -> None:
    _repo(tmp_path)
    _write(tmp_path, "VERSION", "10.0.0")
    with pytest.raises(ProductionReleaseError, match="newline-terminated"):
        collect_active_version_values(tmp_path)
