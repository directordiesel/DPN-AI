from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "v9-desktop.js").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "v9-desktop.css").read_text(encoding="utf-8")


def test_v9_desktop_assets_are_loaded_without_removing_v8_shell():
    assert '/v8-desktop.css' in HTML
    assert '/v8-desktop.js' in HTML
    assert '/v9-desktop.css' in HTML
    assert '/v9-desktop.js' in HTML
    assert 'WINDOWS DESKTOP PLATFORM v8' in HTML


def test_command_palette_maps_existing_control_center_targets():
    assert 'v9CommandPalette' in JS
    assert "['Task Center', 'jobsBtn'" in JS
    assert "['Approval Center', 'approvalsBtn'" in JS
    assert "['Projects & Task Board', 'projectsBtn'" in JS
    assert "['System Settings', 'settingsBtn'" in JS
    assert "event.key.toLowerCase() === 'k'" in JS


def test_live_activity_rail_uses_real_existing_status_cards():
    assert 'desktopMissionCard' in JS
    assert 'desktopApprovalCard' in JS
    assert 'desktopAutomationCard' in JS
    assert 'desktopConnectorCard' in JS
    assert 'MutationObserver' in JS


def test_focus_drawer_routes_to_existing_live_surfaces():
    assert 'v9FocusDrawer' in JS
    assert "openFocus('tasks')" in JS
    assert "openFocus('approvals')" in JS
    assert "openFocus('agents')" in JS
    assert 'data-route="jobsBtn"' in JS
    assert 'data-route="runsBtn"' in JS
    assert 'data-route="approvalsBtn"' in JS
    assert 'data-route="diagnosticsBtn"' in JS


def test_agent_activity_does_not_expose_private_reasoning():
    assert 'without exposing private internal reasoning' in JS
    assert 'not hidden chain-of-thought or private reasoning traces' in JS


def test_pause_resume_cancel_language_is_evidence_first():
    assert 'Pause / Resume / Cancel' in JS
    assert 'never fabricates successful cancellation' in JS


def test_accessibility_and_mobile_fallbacks_exist():
    assert 'aria-live="polite"' in JS
    assert 'role="dialog"' in JS
    assert '.v9-sr-only' in CSS
    assert '@media(max-width:900px)' in CSS
    assert '.v9-focus-drawer' in CSS


def test_dialogs_track_accessibility_state_and_restore_focus():
    assert 'aria-hidden="true"' in JS
    assert "setAttribute('aria-hidden', 'false')" in JS
    assert 'rememberFocus()' in JS
    assert 'restoreFocus()' in JS
    assert "$('v9FocusClose')?.focus()" in JS


def test_keyboard_focus_is_trapped_inside_modal_surfaces():
    assert 'function trapFocus(event, root)' in JS
    assert "event.key !== 'Tab'" in JS
    assert "addEventListener('keydown', (event) => trapFocus(event, $('v9CommandPalette')))" in JS
    assert "addEventListener('keydown', (event) => trapFocus(event, $('v9FocusDrawer')))" in JS


def test_palette_exposes_active_option_to_assistive_technology():
    assert 'aria-controls="v9CommandResults"' in JS
    assert 'aria-activedescendant=""' in JS
    assert 'v9CommandOption${index}' in JS
    assert "input.setAttribute('aria-activedescendant'" in JS


def test_global_shortcuts_do_not_hijack_editable_content():
    assert 'function isEditableTarget(target)' in JS
    assert '[contenteditable="true"]' in JS
    assert "!isEditableTarget(event.target)" in JS
