from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / "mobile" / "android" / "app" / "src" / "main" / "java" / "com" / "dpntechnology" / "dpnai" / "security" / "SecureCredentialStore.kt").read_text(encoding="utf-8")
MAIN = (ROOT / "mobile" / "android" / "app" / "src" / "main" / "java" / "com" / "dpntechnology" / "dpnai" / "MainActivity.kt").read_text(encoding="utf-8")


def test_android_v2_persists_session_and_revocation_metadata():
    assert 'KEY_SESSION_ISSUED_AT' in STORE
    assert 'KEY_DEVICE_REVOKED' in STORE
    assert 'markDeviceRevoked' in STORE
    assert 'isSessionCurrent' in STORE


def test_remote_mode_rejects_revoked_devices_and_uses_shorter_session():
    assert 'revoked device cannot enter remote mode' in STORE
    assert 'MAX_REMOTE_SESSION_SECONDS = 8L * 60L * 60L' in STORE
    assert 'MAX_LOCAL_SESSION_SECONDS = 24L * 60L * 60L' in STORE


def test_expired_or_revoked_credentials_fail_closed_before_api_use():
    assert 'if (isDeviceRevoked() || !isSessionCurrent()) return null' in STORE
    assert 'DEVICE REVOKED • re-pairing required' in MAIN
    assert 'SESSION EXPIRED • secure re-pairing required' in MAIN


def test_main_activity_only_enables_gateway_for_current_trusted_device():
    assert 'gatewayButton.isEnabled = locallyPaired && sessionCurrent && !revoked' in MAIN
    assert 'trusted encrypted session active' in MAIN
