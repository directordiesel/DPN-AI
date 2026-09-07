from __future__ import annotations

import re
from pathlib import Path

from app.production_release_v10 import EXPECTED_STABLE_VERSION, ProductionReleaseError
from app.version_promotion_v10 import ACTIVE_VERSION_SURFACES, TARGET_TAG


_RUNTIME_RE = re.compile(r'^APP_VERSION = "(?P<version>[^"]+)"$', re.MULTILINE)
_README_STABLE_RE = re.compile(r'<strong>Stable release:</strong> (?P<tag>v[^ <]+)')
_SW_CACHE_RE = re.compile(r"const CACHE = 'dpn-ai-(?P<tag>v[^']+)-ui-shell';")
_INDEX_ASSET_RE = re.compile(r'/styles\.css\?v=(?P<version>[0-9A-Za-z.+-]+)')
_APP_SW_RE = re.compile(r"/sw\.js\?v=(?P<version>[0-9A-Za-z.+-]+)")
_ROADMAP_RE = re.compile(r'Current stable baseline:\s*\*\*(?P<tag>v[^*]+)\*\*')


def _read(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProductionReleaseError(f"unable to read governed version surface {relative}") from exc


def _extract(pattern: re.Pattern[str], text: str, *, group: str, surface: str) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ProductionReleaseError(
            f"governed version surface {surface} must contain exactly one recognized identity; found {len(matches)}"
        )
    return matches[0].group(group)


def collect_active_version_values(repository_root: str | Path) -> dict[str, str]:
    root = Path(repository_root).resolve()
    if not root.is_dir():
        raise ProductionReleaseError("repository root must be an existing directory")

    version_text = _read(root, "VERSION")
    if not version_text.endswith("\n") or version_text.count("\n") != 1:
        raise ProductionReleaseError("VERSION must contain exactly one newline-terminated version value")
    version = version_text[:-1]

    main_text = _read(root, "app/main.py")
    readme_text = _read(root, "README.md")
    sw_text = _read(root, "app/static/sw.js")
    index_text = _read(root, "app/static/index.html")
    app_text = _read(root, "app/static/app.js")
    roadmap_text = _read(root, "ROADMAP.md")

    values = {
        "VERSION": version,
        "app_runtime": _extract(_RUNTIME_RE, main_text, group="version", surface="app_runtime"),
        "readme_stable_identity": _extract(
            _README_STABLE_RE, readme_text, group="tag", surface="readme_stable_identity"
        ),
        "service_worker_cache": _extract(
            _SW_CACHE_RE, sw_text, group="tag", surface="service_worker_cache"
        ),
        "static_index_assets": _extract(
            _INDEX_ASSET_RE, index_text, group="version", surface="static_index_assets"
        ),
        "static_app_service_worker": _extract(
            _APP_SW_RE, app_text, group="version", surface="static_app_service_worker"
        ),
        "roadmap_current_baseline": _extract(
            _ROADMAP_RE, roadmap_text, group="tag", surface="roadmap_current_baseline"
        ),
    }
    if tuple(values) != ACTIVE_VERSION_SURFACES:
        raise ProductionReleaseError("repository version auditor drifted from governed active surface order")
    return values


def require_promoted_repository_versions(repository_root: str | Path) -> dict[str, str]:
    from app.version_promotion_v10 import evaluate_version_promotion

    values = collect_active_version_values(repository_root)
    evaluation = evaluate_version_promotion(values)
    if evaluation.target_version != EXPECTED_STABLE_VERSION or evaluation.target_tag != TARGET_TAG:
        raise ProductionReleaseError("repository promotion evaluation returned an unexpected target identity")
    return values


__all__ = ["collect_active_version_values", "require_promoted_repository_versions"]
