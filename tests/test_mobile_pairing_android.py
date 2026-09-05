from __future__ import annotations

from pathlib import Path


ROOT = Path("mobile/android/app/src/main")


def test_pairing_activity_is_native_non_exported_and_control_center_reachable() -> None:
    manifest = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")
    main = (ROOT / "java/com/dpntechnology/dpnai/MainActivity.kt").read_text(encoding="utf-8")
    pairing = (ROOT / "java/com/dpntechnology/dpnai/PairingActivity.kt").read_text(encoding="utf-8")

    assert '<activity android:name=".PairingActivity" android:exported="false" />' in manifest
    assert "PairingActivity::class.java" in main
    assert "Secure Desktop Pairing" in main
    assert "PairingApiClient().completePairing" in pairing
    assert "credentialStore.saveDesktopCredential" in pairing


def test_pairing_client_uses_only_https_exact_pairing_surface_and_refuses_redirects() -> None:
    source = (ROOT / "java/com/dpntechnology/dpnai/network/PairingApiClient.kt").read_text(encoding="utf-8")

    assert 'private const val PAIRING_PATH = "/mobile/v1/pairing/complete"' in source
    assert 'uri.scheme.equals("https", ignoreCase = true)' in source
    assert "instanceFollowRedirects = false" in source
    assert "connectTimeout = CONNECT_TIMEOUT_MS" in source
    assert "readTimeout = READ_TIMEOUT_MS" in source
    assert "MAX_RESPONSE_CHARS" in source
    assert 'setRequestProperty("X-DPN-Token"' not in source
    assert 'setRequestProperty("X-DPN-Device-ID"' not in source


def test_pairing_ui_never_requests_desktop_wide_access_token() -> None:
    pairing = (ROOT / "java/com/dpntechnology/dpnai/PairingActivity.kt").read_text(encoding="utf-8")
    client = (ROOT / "java/com/dpntechnology/dpnai/network/PairingApiClient.kt").read_text(encoding="utf-8")

    combined = pairing + client
    assert "DPN_ACCESS_TOKEN" not in combined
    assert "desktop-wide API token is never entered on Android" in pairing
    assert "challengeId" in pairing
    assert "secret" in pairing


def test_successful_pairing_flows_into_existing_keystore_credential_store() -> None:
    pairing = (ROOT / "java/com/dpntechnology/dpnai/PairingActivity.kt").read_text(encoding="utf-8")
    store = (ROOT / "java/com/dpntechnology/dpnai/security/SecureCredentialStore.kt").read_text(encoding="utf-8")

    assert "credentialStore.saveDesktopCredential(baseUrl, it.deviceId, it.token)" in pairing
    assert 'KeyStore.getInstance("AndroidKeyStore")' in store
    assert 'private const val TRANSFORMATION = "AES/GCM/NoPadding"' in store
    assert ".putString(KEY_LOCAL_TOKEN, encrypt(token))" in store
    assert ".putString(KEY_DEVICE_ID, encrypt(deviceId))" in store
