from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/security/SecureCredentialStore.kt"
GATEWAY = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/GatewayActivity.kt"
MAIN = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/MainActivity.kt"
MANIFEST = ROOT / "mobile/android/app/src/main/AndroidManifest.xml"
SERVER = ROOT / "app/main.py"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_remote_gateway_requires_https_and_non_loopback():
    source = text(STORE)
    assert 'scheme.equals("https"' in source
    assert "remote gateway must not use a loopback host" in source
    assert "endpoint must not contain embedded credentials" in source


def test_remote_credentials_are_separate_and_keystore_encrypted():
    source = text(STORE)
    assert "KEY_REMOTE_ENDPOINT" in source
    assert "KEY_REMOTE_TOKEN" in source
    assert "AndroidKeyStore" in source
    assert "AES/GCM/NoPadding" in source
    assert "saveRemoteGateway" in source
    assert "loadLocalCredential" in source


def test_remote_mode_requires_local_pairing_and_manual_switch():
    store = text(STORE)
    activity = text(GATEWAY)
    assert "pair this device locally before enabling remote gateway access" in store
    assert "setRemoteMode" in store
    assert 'text = "Use Remote Gateway"' in activity
    assert 'text = "Use Local Desktop"' in activity
    assert "WorkManager" not in activity
    assert "JobService" not in activity
    assert "AlarmManager" not in activity


def test_gateway_activity_is_internal_and_pairing_gated():
    manifest = text(MANIFEST)
    main = text(MAIN)
    assert '<activity android:name=".GatewayActivity" android:exported="false" />' in manifest
    assert 'text = "Secure Remote Gateway"' in main
    assert "gatewayButton.isEnabled = locallyPaired" in main


def test_server_remote_access_stays_fail_closed_without_access_token():
    server = text(SERVER)
    assert "Remote API access is disabled until DPN_ACCESS_TOKEN is configured." in server
    assert 'request.headers.get("X-DPN-Token"' in server


def test_gateway_control_does_not_bypass_approval_or_launch_missions():
    source = text(GATEWAY)
    assert "ApprovalApiClient" not in source
    assert "MissionApiClient" not in source
    assert "decide(" not in source
    assert "launchMission(" not in source
