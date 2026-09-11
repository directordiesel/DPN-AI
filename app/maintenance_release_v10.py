from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


class MaintenanceReleaseError(ValueError):
    """Raised when DPN AI v10.0.1 maintenance-release evidence is incomplete or ambiguous."""


BASE_STABLE_VERSION = "10.0.0"
TARGET_VERSION = "10.0.1"
TARGET_TAG = f"v{TARGET_VERSION}"
CHECKPOINT = "v10.0.1-maintenance-readiness"


@dataclass(frozen=True)
class MaintenanceReleaseFamily:
    family: str
    test_id: str
    description: str


_REQUIRED_FAMILIES: tuple[MaintenanceReleaseFamily, ...] = (
    MaintenanceReleaseFamily(
        "desktop_encoding_integrity",
        "tests/test_v10_0_1_usability.py::test_user_facing_sources_contain_no_known_mojibake_markers",
        "Desktop and Android user-facing sources must remain free of known encoding corruption.",
    ),
    MaintenanceReleaseFamily(
        "desktop_dom_integrity",
        "tests/test_v10_0_1_usability.py::test_literal_dom_references_resolve_and_static_ids_are_unique",
        "Literal desktop DOM references must resolve and static IDs must remain unique.",
    ),
    MaintenanceReleaseFamily(
        "modal_accessibility",
        "tests/test_v10_0_1_usability.py::test_modal_supports_scrolling_semantics_escape_focus_trap_and_focus_restore",
        "Primary modal interaction must preserve scrolling, semantics, keyboard containment, and focus restoration.",
    ),
    MaintenanceReleaseFamily(
        "actionable_error_recovery",
        "tests/test_v10_0_1_usability.py::test_errors_are_actionable_bounded_and_redacted",
        "Normal user-facing errors must be bounded, redacted, and paired with a recovery action.",
    ),
    MaintenanceReleaseFamily(
        "capability_recovery_guidance",
        "tests/test_v10_0_1_usability.py::test_unavailable_capabilities_explain_recovery_in_plain_language",
        "Unavailable capabilities must explain what is missing and how to recover.",
    ),
    MaintenanceReleaseFamily(
        "technical_evidence_presentation",
        "tests/test_v10_0_1_usability.py::test_expert_evidence_is_human_first_and_explicitly_labeled",
        "Expert evidence must remain exact while normal presentation stays human-first.",
    ),
    MaintenanceReleaseFamily(
        "mobile_scrollability",
        "tests/test_mobile_polish.py::test_every_primary_android_screen_is_scrollable",
        "Every primary Android surface must remain reachable on bounded displays.",
    ),
    MaintenanceReleaseFamily(
        "mobile_action_wiring",
        "tests/test_mobile_polish.py::test_programmatic_android_buttons_have_click_handlers",
        "Every programmatic Android button must retain an explicit click action.",
    ),
    MaintenanceReleaseFamily(
        "mobile_safe_recovery",
        "tests/test_mobile_polish.py::test_mobile_connection_failures_direct_users_to_safe_diagnostics",
        "Mobile connection failures must direct users to safe diagnostics without leaking raw exceptions.",
    ),
    MaintenanceReleaseFamily(
        "mobile_voice_recovery",
        "tests/test_mobile_polish.py::test_mobile_voice_unavailability_has_a_recovery_path",
        "Mobile voice unavailability must offer a usable fallback or setup path.",
    ),
    MaintenanceReleaseFamily(
        "maintenance_version_surface_coherence",
        "tests/test_maintenance_release_v10.py::test_repository_candidate_version_surfaces_are_coherent",
        "The active candidate surfaces must agree on v10.0.1 while preserving v10.0.0 as the published stable baseline.",
    ),
)


def maintenance_release_manifest() -> dict[str, str]:
    return {item.family: item.test_id for item in _REQUIRED_FAMILIES}


def maintenance_release_families() -> tuple[MaintenanceReleaseFamily, ...]:
    return _REQUIRED_FAMILIES


def audit_maintenance_release(evidence: Mapping[str, object]) -> dict:
    if not isinstance(evidence, Mapping):
        raise MaintenanceReleaseError("maintenance release evidence must be a mapping")
    manifest = maintenance_release_manifest()
    missing = [family for family in manifest if family not in evidence]
    unexpected = sorted(set(evidence) - set(manifest))
    failed: list[str] = []
    for family in manifest:
        value = evidence.get(family)
        if type(value) is not bool or value is not True:
            failed.append(family)
    ready = not missing and not unexpected and not failed
    return {
        "schema_version": 1,
        "checkpoint": CHECKPOINT,
        "base_stable_version": BASE_STABLE_VERSION,
        "target_version": TARGET_VERSION,
        "target_tag": TARGET_TAG,
        "ready": ready,
        "required_families": list(manifest),
        "required_test_ids": list(manifest.values()),
        "missing_families": missing,
        "failed_families": failed,
        "unexpected_families": unexpected,
        "execution_authorized": False,
        "release_publish_authorized": False,
    }


def require_maintenance_release(evidence: Mapping[str, object]) -> dict:
    audit = audit_maintenance_release(evidence)
    if not audit["ready"]:
        raise MaintenanceReleaseError("v10.0.1 maintenance release evidence is incomplete or failed")
    return audit


_RUNTIME_RE = re.compile(r'^APP_VERSION = "(?P<version>[^"]+)"$', re.MULTILINE)
_README_STABLE_RE = re.compile(r'<strong>Stable release:</strong> (?P<tag>v[^ <]+)')
_README_CANDIDATE_RE = re.compile(r'<strong>Maintenance candidate:</strong> (?P<tag>v[^ <]+)')
_SW_CACHE_RE = re.compile(r"const CACHE = 'dpn-ai-(?P<tag>v[^']+)-ui-shell';")
_INDEX_STYLE_RE = re.compile(r'/styles\.css\?v=(?P<version>[0-9A-Za-z.+-]+)')
_INDEX_APP_RE = re.compile(r'/app\.js\?v=(?P<version>[0-9A-Za-z.+-]+)')
_APP_SW_RE = re.compile(r"/sw\.js\?v=(?P<version>[0-9A-Za-z.+-]+)")
_ROADMAP_STABLE_RE = re.compile(r'Current stable baseline:\s*\*\*(?P<tag>v[^*]+)\*\*')
_ROADMAP_ACTIVE_RE = re.compile(r'Active engineering direction:\s*\*\*(?P<text>[^*]+)\*\*')
_ANDROID_DEV_RE = re.compile(r'releaseVersionName = .*?\?: "(?P<version>[^"]+)"')


def _read(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MaintenanceReleaseError(f"unable to read maintenance version surface {relative}") from exc


def _extract(pattern: re.Pattern[str], text: str, *, group: str, label: str) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise MaintenanceReleaseError(
            f"maintenance version surface {label} must contain exactly one recognized identity; found {len(matches)}"
        )
    return matches[0].group(group)


def collect_maintenance_version_surfaces(repository_root: str | Path) -> dict[str, str]:
    root = Path(repository_root).resolve()
    if not root.is_dir():
        raise MaintenanceReleaseError("repository root must be an existing directory")

    version_text = _read(root, "VERSION")
    if not version_text.endswith("\n") or version_text.count("\n") != 1:
        raise MaintenanceReleaseError("VERSION must contain exactly one newline-terminated version value")

    main = _read(root, "app/main.py")
    readme = _read(root, "README.md")
    sw = _read(root, "app/static/sw.js")
    index = _read(root, "app/static/index.html")
    app_js = _read(root, "app/static/app.js")
    roadmap = _read(root, "ROADMAP.md")
    android_gradle = _read(root, "mobile/android/app/build.gradle.kts")

    return {
        "VERSION": version_text[:-1],
        "app_runtime": _extract(_RUNTIME_RE, main, group="version", label="app_runtime"),
        "readme_stable": _extract(_README_STABLE_RE, readme, group="tag", label="readme_stable"),
        "readme_candidate": _extract(_README_CANDIDATE_RE, readme, group="tag", label="readme_candidate"),
        "service_worker_cache": _extract(_SW_CACHE_RE, sw, group="tag", label="service_worker_cache"),
        "service_worker_styles": _extract(_INDEX_STYLE_RE, sw, group="version", label="service_worker_styles"),
        "service_worker_app": _extract(_INDEX_APP_RE, sw, group="version", label="service_worker_app"),
        "index_styles": _extract(_INDEX_STYLE_RE, index, group="version", label="index_styles"),
        "index_app": _extract(_INDEX_APP_RE, index, group="version", label="index_app"),
        "app_service_worker": _extract(_APP_SW_RE, app_js, group="version", label="app_service_worker"),
        "roadmap_stable": _extract(_ROADMAP_STABLE_RE, roadmap, group="tag", label="roadmap_stable"),
        "roadmap_active": _extract(_ROADMAP_ACTIVE_RE, roadmap, group="text", label="roadmap_active"),
        "android_development_version": _extract(
            _ANDROID_DEV_RE, android_gradle, group="version", label="android_development_version"
        ),
    }


def require_maintenance_version_surfaces(repository_root: str | Path) -> dict[str, str]:
    values = collect_maintenance_version_surfaces(repository_root)
    expected = {
        "VERSION": TARGET_VERSION,
        "app_runtime": TARGET_VERSION,
        "readme_stable": f"v{BASE_STABLE_VERSION}",
        "readme_candidate": TARGET_TAG,
        "service_worker_cache": TARGET_TAG,
        "service_worker_styles": TARGET_VERSION,
        "service_worker_app": TARGET_VERSION,
        "index_styles": TARGET_VERSION,
        "index_app": TARGET_VERSION,
        "app_service_worker": TARGET_VERSION,
        "roadmap_stable": f"v{BASE_STABLE_VERSION}",
        "roadmap_active": "v10.0.1 maintenance hardening and release-candidate validation",
        "android_development_version": f"{TARGET_VERSION}-dev",
    }
    if set(values) != set(expected):
        raise MaintenanceReleaseError("maintenance version surface set drifted from the governed contract")
    for surface, expected_value in expected.items():
        if values[surface] != expected_value:
            raise MaintenanceReleaseError(
                f"maintenance version surface {surface} must be exactly {expected_value!r}; got {values[surface]!r}"
            )
    return values


__all__ = [
    "BASE_STABLE_VERSION",
    "CHECKPOINT",
    "MaintenanceReleaseError",
    "MaintenanceReleaseFamily",
    "TARGET_TAG",
    "TARGET_VERSION",
    "audit_maintenance_release",
    "collect_maintenance_version_surfaces",
    "maintenance_release_families",
    "maintenance_release_manifest",
    "require_maintenance_release",
    "require_maintenance_version_surfaces",
]
