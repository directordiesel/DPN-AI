from pathlib import Path
import re


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


def test_primary_modules_explain_purpose_first_action_and_safety():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "function moduleIntro(title, purpose, firstAction, safety = '')" in js
    assert "What is this?" in js
    assert "Start here:" in js
    assert "Safety:" in js

    for module in (
        "Voice Command Center",
        "Workspace Files",
        "Local Memory",
        "Projects & Task Board",
        "Local Automations",
        "Runs & Audit Trail",
        "Workspace Snapshots",
        "System Diagnostics",
        "Universal Missions",
        "Autonomous Job Queue",
        "Knowledge Graph",
        "Sandbox Lab",
        "Capability Forge",
        "Tool Server Connections (MCP)",
        "Approval Inbox",
        "Skills & Workflows",
        "Connectors & Secrets",
    ):
        assert "moduleIntro('" + module + "'" in js


def test_destructive_memory_delete_requires_confirmation():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "Delete this saved memory?" in js
    delete_call = "api(`/api/memories/${button.dataset.memory}`, {method:'DELETE'})"
    assert delete_call in js
    assert js.index("Delete this saved memory?") < js.index(delete_call)



def test_desktop_shell_source_uses_plain_ascii_ui_copy():
    for name in ("index.html", "app.js", "v8-desktop.js", "v9-desktop.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        non_ascii = sorted({char for char in text if ord(char) > 127})
        assert not non_ascii, f"{name} contains non-ASCII UI characters: {non_ascii}"

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert ">Menu</button>" in html
    assert ">Reindex</button>" in html
    assert ">Stop</button>" in html
    assert ">Voice Settings</button>" in html
    assert ">Send</button>" in html
    assert ">Close</button>" in html

    v9 = (STATIC / "v9-desktop.js").read_text(encoding="utf-8")
    assert ">Commands</button>" in v9


def test_literal_dom_references_resolve_and_static_ids_are_unique():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("app.js", "v8-desktop.js", "v9-desktop.js")
    )
    markup = html + "\n" + scripts

    declared = set(re.findall(r'\bid=["\']([^"\'$}{]+)["\']', markup))
    references = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", scripts))
    references.update(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", scripts))

    assert references - declared == set()

    static_ids = re.findall(r'\bid=["\']([^"\']+)["\']', html)
    duplicates = sorted({item for item in static_ids if static_ids.count(item) > 1})
    assert duplicates == []


def test_every_static_button_with_an_id_is_wired_in_desktop_javascript():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("app.js", "v8-desktop.js", "v9-desktop.js")
    )
    button_ids = re.findall(r'<button\b[^>]*\bid="([^"]+)"', html)
    missing = [button_id for button_id in button_ids if button_id not in scripts]
    assert missing == []


def test_modal_supports_scrolling_semantics_escape_focus_trap_and_focus_restore():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="modalTitle"' in html
    assert 'id="modalBackdrop" aria-hidden="true"' in html

    assert "let modalReturnFocus = null" in js
    assert "function modalIsOpen()" in js
    assert "function modalFocusableElements()" in js
    assert "function trapModalFocus(event)" in js
    assert "event.key === 'Tab' && modalIsOpen()" in js
    assert "els.modalBackdrop.setAttribute('aria-hidden', 'false')" in js
    assert "els.modalBackdrop.setAttribute('aria-hidden', 'true')" in js
    assert "document.contains(target)" in js
    assert "target.focus({preventScroll:true})" in js
    assert "if (modalIsOpen()) { event.preventDefault(); closeModal(); return; }" in js

    assert ".modal-body {" in css
    assert "overflow: auto;" in css
    assert "max-height: calc(var(--dpn-viewport-height) - 28px);" in css


def test_user_visible_desktop_copy_has_no_stale_v5_labels():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "v5.0.7 clarity engine" not in js
    assert "DPN AI v5 sandbox ready" not in js
    assert "Legacy model active:" not in js
    assert "DPN AI sandbox ready" in js
    assert "The local voice engine uses the highest-quality installed voice model" in js


def test_all_delete_requests_have_human_confirmation_nearby():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    lines = js.splitlines()
    delete_lines = [index for index, line in enumerate(lines) if "method:'DELETE'" in line or 'method:"DELETE"' in line]
    assert delete_lines
    unconfirmed = []
    for index in delete_lines:
        nearby = "\n".join(lines[max(0, index - 3): index + 1])
        if "confirm(" not in nearby:
            unconfirmed.append(index + 1)
    assert unconfirmed == []
