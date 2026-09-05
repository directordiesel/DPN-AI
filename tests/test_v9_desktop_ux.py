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
    assert "['Approval Inbox', 'approvalsBtn'" in JS
    assert "['Projects & Task Board', 'projectsBtn'" in JS
    assert "['System Settings', 'settingsBtn'" in JS
    assert "event.key.toLowerCase() === 'k'" in JS


def test_live_activity_rail_uses_real_existing_status_cards():
    assert 'desktopMissionCard' in JS
    assert 'desktopApprovalCard' in JS
    assert 'desktopAutomationCard' in JS
    assert 'desktopConnectorCard' in JS
    assert 'MutationObserver' in JS


def test_accessibility_and_mobile_fallbacks_exist():
    assert 'aria-live="polite"' in JS
    assert 'role="dialog"' in JS
    assert '.v9-sr-only' in CSS
    assert '@media(max-width:900px)' in CSS
