from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "v9-desktop.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "v9-desktop.css").read_text(encoding="utf-8")


def test_legacy_assets_can_load_without_exposing_legacy_product_branding():
    assert '/v8-desktop.css' in HTML
    assert '/v8-desktop.js' in HTML
    assert '/v9-desktop.css' in HTML
    assert '/v9-desktop.js' in HTML
    assert 'WINDOWS DESKTOP PLATFORM v8' not in HTML
    assert 'DPN AI DESKTOP PLATFORM' in HTML


def test_command_palette_maps_existing_control_center_targets():
    assert 'v9CommandPalette' in JS
    assert "['Task Center', 'jobsBtn'" in JS
    assert "['Approval Center', 'approvalsBtn'" in JS
    assert "['Projects & Task Board', 'projectsBtn'" in JS
    assert "['System Settings', 'settingsBtn'" in JS
    assert "event.key.toLowerCase() === 'k'" in JS


def test_live_activity_rail_is_removed_without_removing_dashboard_status():
    assert 'v9ActivityRail' not in JS
    assert 'v9ActivityToggle' not in JS
    assert 'LIVE ACTIVITY' not in JS
    assert '.v9-activity-rail' not in CSS
    assert '.v9-activity-grid' not in CSS
    assert 'desktopMissionCard' in HTML
    assert 'desktopApprovalCard' in HTML
    assert 'desktopAutomationCard' in HTML
    assert 'desktopConnectorCard' in HTML


def test_observer_only_announces_real_dashboard_updates_accessibly():
    assert 'MutationObserver' in JS
    assert 'v9LiveRegion' in JS
    assert 'desktopApprovalCard' in JS
    assert 'mirrorDesktopSummary' not in JS


def test_accessibility_and_mobile_command_palette_fallbacks_exist():
    assert 'aria-live="polite"' in JS
    assert 'role="dialog"' in JS
    assert '.v9-sr-only' in CSS
    assert '@media(max-width:900px)' in CSS
    assert '.v9-command-palette' in CSS


def test_command_palette_tracks_accessibility_state_and_restores_focus():
    assert 'aria-hidden="true"' in JS
    assert "setAttribute('aria-hidden', 'false')" in JS
    assert 'rememberFocus()' in JS
    assert 'restoreFocus()' in JS
    assert "$('v9CommandInput')?.focus()" in JS


def test_keyboard_focus_is_trapped_inside_command_palette():
    assert 'function trapFocus(event, root)' in JS
    assert "event.key !== 'Tab'" in JS
    assert "addEventListener('keydown', (event) => trapFocus(event, $('v9CommandPalette')))" in JS
    assert 'v9FocusDrawer' not in JS


def test_palette_exposes_active_option_to_assistive_technology():
    assert 'aria-controls="v9CommandResults"' in JS
    assert 'aria-activedescendant=""' in JS
    assert 'v9CommandOption${index}' in JS
    assert "input.setAttribute('aria-activedescendant'" in JS


def test_global_shortcuts_do_not_hijack_editable_content():
    assert 'function isEditableTarget(target)' in JS
    assert '[contenteditable="true"]' in JS
    assert "!isEditableTarget(event.target)" in JS
