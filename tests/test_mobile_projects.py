from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/network/DesktopApiClient.kt"
ACTIVITY = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/ProjectsActivity.kt"
MAIN = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/MainActivity.kt"
MANIFEST = ROOT / "mobile/android/app/src/main/AndroidManifest.xml"


def test_projects_use_shared_backend_contracts():
    text = CLIENT.read_text(encoding="utf-8")
    for route in ("/api/projects", "/api/projects/$safeId/tasks", "/api/tasks/$safeTask"):
        assert route in text
    assert 'setRequestProperty("X-DPN-Token"' in text
    assert 'setRequestProperty("X-DPN-Device-ID"' in text


def test_mobile_project_creation_is_workspace_bounded():
    text = CLIENT.read_text(encoding="utf-8")
    assert 'require(rootPath == ".")' in text
    assert 'mobile project creation is restricted to the DPN AI workspace root' in text


def test_task_state_and_priority_are_bounded():
    text = CLIENT.read_text(encoding="utf-8")
    assert 'ALLOWED_PRIORITIES = setOf("low", "normal", "high", "critical")' in text
    assert 'ALLOWED_TASK_STATUSES = setOf("backlog", "ready", "running", "blocked", "done", "failed")' in text


def test_projects_console_is_pairing_gated_and_internal():
    main = MAIN.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert 'addCapability(root, "Projects & Tasks", ProjectsActivity::class.java)' in main
    assert 'setCapabilityButtons(active)' in main
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in main
    assert 'android:name=".ProjectsActivity" android:exported="false"' in manifest


def test_projects_console_has_explicit_user_actions_only():
    text = ACTIVITY.read_text(encoding="utf-8")
    assert "Create Project" in text
    assert "Create Task" in text
    assert "Mark Task Ready" in text
    assert "Mark Task Running" in text
    assert "Mark Task Done" in text
    assert "WorkManager" not in text
    assert "Service" not in text
