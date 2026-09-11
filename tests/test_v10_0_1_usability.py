from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ANDROID_MAIN = ROOT / "mobile" / "android" / "app" / "src" / "main"

BROKEN_ENCODING_MARKERS = {
    "â": "UTF-8 text decoded as a legacy single-byte encoding",
    "Ã": "UTF-8 multibyte text decoded incorrectly",
    "\ufffd": "Unicode replacement character",
}


def _user_facing_sources() -> list[Path]:
    paths = []
    for pattern in ("*.html", "*.js", "*.css"):
        paths.extend(STATIC.glob(pattern))
    if ANDROID_MAIN.exists():
        paths.extend(ANDROID_MAIN.rglob("*.kt"))
        paths.extend(ANDROID_MAIN.rglob("*.xml"))
    return sorted(path for path in paths if path.is_file())


def test_user_facing_sources_contain_no_known_mojibake_markers():
    failures = []
    for path in _user_facing_sources():
        text = path.read_text(encoding="utf-8")
        for marker, meaning in BROKEN_ENCODING_MARKERS.items():
            if marker in text:
                failures.append(f"{path.relative_to(ROOT)} contains {marker!r}: {meaning}")
    assert not failures, "\n".join(failures)


def test_live_activity_overlay_is_fully_removed_not_merely_collapsed():
    js = (STATIC / "v9-desktop.js").read_text(encoding="utf-8")
    css = (STATIC / "v9-desktop.css").read_text(encoding="utf-8")

    for token in (
        "v9ActivityRail",
        "v9ActivityToggle",
        "v9ActivityState",
        "v9MissionCount",
        "v9ApprovalCount",
        "v9AutomationCount",
        "v9ConnectorCount",
        "LIVE ACTIVITY",
        "mirrorDesktopSummary",
    ):
        assert token not in js

    assert ".v9-activity-rail" not in css
    assert ".v9-activity-grid" not in css
    assert ".v9-activity-rail.collapsed" not in css


def test_main_dashboard_status_cards_remain_after_overlay_removal():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "desktopCoreCard",
        "desktopMissionCard",
        "desktopApprovalCard",
        "desktopModelCard",
        "desktopAutomationCard",
        "desktopConnectorCard",
    ):
        assert f'id="{element_id}"' in html


def test_activity_overlay_cleanup_does_not_leave_orphaned_focus_ui():
    js = (STATIC / "v9-desktop.js").read_text(encoding="utf-8")
    css = (STATIC / "v9-desktop.css").read_text(encoding="utf-8")

    assert "v9FocusDrawer" not in js
    assert "v9FocusClose" not in js
    assert ".v9-focus-drawer" not in css
    assert ".v9-focus-grid" not in css


def test_settings_are_grouped_and_explained_in_plain_language():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for section in (
        "General",
        "AI Models",
        "Permissions & Safety",
        "Web & Browser",
        "Voice & Media",
        "Automations",
        "Connectors",
        "Files & Workspace",
        "Advanced",
    ):
        assert "title:'" + section + "'" in js

    assert "Configure DPN AI without guessing" in js
    assert "Load Recommended Settings" in js
    assert "Tool Server Connections (MCP)" in js
    assert "Search and memory matching model" in js
    assert "High risk" in js


def test_normal_settings_do_not_require_raw_model_route_json():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="settingModelRoutes"' not in js
    assert "JSON.parse($('settingModelRoutes')" not in js
    assert "data-model-route-row" in js
    assert "data-route-profile" in js
    assert "data-route-model" in js
    assert "addModelRouteBtn" in js
    assert "collectSettingsModelRoutes" in js
    assert "A work profile can only have one preferred model" in js


def test_sidebar_uses_plain_labels_instead_of_decorative_glyph_prefixes():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert "WINDOWS DESKTOP PLATFORM v8" not in html
    assert "DPN AI DESKTOP PLATFORM" in html
    assert "MCP Tool Bridge" not in html
    assert "Tool Server Connections (MCP)" in html

    for glyph in ("◉", "▰", "⬢", "▧", "✧", "⇌", "⚠", "◆", "◷", "⌁", "⬡", "▣", "◈", "✦", "⇄"):
        assert glyph not in html
