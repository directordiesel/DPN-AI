from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "app" / "static" / "v8-desktop.css").read_text(encoding="utf-8")
JS = (ROOT / "app" / "static" / "v8-desktop.js").read_text(encoding="utf-8")


def test_v8_desktop_assets_are_linked():
    assert '/v8-desktop.css' in HTML
    assert '/v8-desktop.js' in HTML
    assert 'WINDOWS DESKTOP PLATFORM v8' in HTML


def test_desktop_status_surfaces_are_explicit_and_not_simulated():
    for card_id in (
        'desktopCoreCard',
        'desktopMissionCard',
        'desktopApprovalCard',
        'desktopModelCard',
        'desktopAutomationCard',
        'desktopConnectorCard',
    ):
        assert card_id in HTML
    assert 'No simulated production metrics are displayed.' in HTML
    assert 'Waiting for mission summary API' in HTML
    assert 'Waiting for connector health summary API' in HTML


def test_desktop_workspace_navigation_is_present():
    for workspace in ('chat', 'missions', 'projects', 'creator', 'research', 'automation', 'diagnostics'):
        assert f'data-workspace="{workspace}"' in HTML
    assert 'dpn-ai-v8-workspace' in JS


def test_desktop_runtime_probe_is_loopback_service_relative():
    assert "core: '/api/health'" in JS
    assert 'fetch(STATUS_ENDPOINTS.core' in JS
    assert 'http://0.0.0.0' not in JS
    assert 'https://0.0.0.0' not in JS


def test_desktop_quick_actions_reuse_existing_controls():
    for existing_id in ('missionsBtn', 'approvalsBtn', 'projectsBtn', 'diagnosticsBtn'):
        assert existing_id in JS
    assert 'invokeExisting' in JS


def test_desktop_theme_uses_v8_purple_layer():
    assert '--v8-purple: #8b5cf6' in CSS
    assert 'body.desktop-v8 .app-shell' in CSS
    assert '.desktop-status-grid' in CSS
