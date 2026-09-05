from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android" / "app" / "src" / "main"


def read(path: str) -> str:
    return (ANDROID / path).read_text(encoding="utf-8")


def test_notification_activity_is_internal_and_permission_is_declared():
    manifest = read("AndroidManifest.xml")
    assert 'android.permission.POST_NOTIFICATIONS' in manifest
    assert 'android:name=".NotificationsActivity" android:exported="false"' in manifest


def test_notifications_require_explicit_refresh_and_do_not_background_poll():
    source = read("java/com/dpntechnology/dpnai/NotificationsActivity.kt")
    assert "Refresh Notification Center" in source
    assert "setOnClickListener { refreshFeed(postSystemNotifications = true) }" in source
    forbidden = ["WorkManager", "JobService", "AlarmManager", "ForegroundService", "startForegroundService"]
    for token in forbidden:
        assert token not in source


def test_notifications_reuse_shared_mission_and_approval_clients():
    source = read("java/com/dpntechnology/dpnai/NotificationsActivity.kt")
    assert "MissionApiClient(credentialStore).listMissions" in source
    assert 'ApprovalApiClient(credentialStore).listApprovals(status = "pending"' in source
    assert "decide(" not in source
    assert "launchMission(" not in source


def test_notification_permission_is_requested_only_for_system_notifications():
    source = read("java/com/dpntechnology/dpnai/NotificationsActivity.kt")
    assert "Build.VERSION.SDK_INT >= 33" in source
    assert "Manifest.permission.POST_NOTIFICATIONS" in source
    assert "requestPermissions" in source


def test_main_control_center_pairing_gates_notifications():
    source = read("java/com/dpntechnology/dpnai/MainActivity.kt")
    assert 'addCapability(root, "Notification Center", NotificationsActivity::class.java)' in source
    assert 'setCapabilityButtons(active)' in source
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in source
