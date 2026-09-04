from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = (ROOT / "desktop" / "service.py").read_text(encoding="utf-8")
SUPERVISOR = (ROOT / "desktop" / "supervisor.py").read_text(encoding="utf-8")
DESKTOP_JS = (ROOT / "app" / "static" / "v8-desktop.js").read_text(encoding="utf-8")


def test_desktop_service_reuses_unified_runtime():
    assert "from app.main import app, db, agent" in SERVICE
    assert "FastAPI(" not in SERVICE
    assert "Database(" not in SERVICE
    assert "DPNAIAgent(" not in SERVICE


def test_desktop_api_is_versioned_and_secret_free_by_contract():
    assert 'DESKTOP_API_VERSION = "v1"' in SERVICE
    assert '@app.get("/api/v1/desktop/summary")' in SERVICE
    assert '@app.get("/api/v1/desktop/events")' in SERVICE
    assert '"connectors": {' in SERVICE
    assert '"total": len(connectors)' in SERVICE
    assert 'secret' not in SERVICE.lower().split('def desktop_summary', 1)[1].split('@app.get', 1)[0]


def test_desktop_event_stream_is_sse_and_bounded():
    assert 'media_type="text/event-stream"' in SERVICE
    assert 'event: desktop.summary' in SERVICE
    assert 'await asyncio.sleep(2.0)' in SERVICE
    assert 'Cache-Control' in SERVICE


def test_static_catch_all_is_kept_after_v8_api_routes():
    assert 'def _keep_static_mount_last()' in SERVICE
    assert 'getattr(route, "name", None) == "static"' in SERVICE
    assert 'app.router.routes.extend(static_routes)' in SERVICE


def test_supervisor_launches_desktop_service_facade():
    assert 'module: str = "desktop.service:app"' in SUPERVISOR
    assert '("desktop/service.py",)' in SUPERVISOR


def test_desktop_client_uses_authenticated_summary_and_stream_endpoints():
    assert "summary: '/api/v1/desktop/summary'" in DESKTOP_JS
    assert "events: '/api/v1/desktop/events'" in DESKTOP_JS
    assert "sessionStorage.getItem('dpnApiToken')" in DESKTOP_JS
    assert "'X-DPN-Token': token" in DESKTOP_JS
    assert "Accept: 'text/event-stream'" in DESKTOP_JS
    assert "renderSummary(JSON.parse" in DESKTOP_JS
