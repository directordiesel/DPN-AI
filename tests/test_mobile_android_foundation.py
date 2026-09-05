from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android"
MANIFEST = (ANDROID / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
STORE = (ANDROID / "app" / "src" / "main" / "java" / "com" / "dpntechnology" / "dpnai" / "security" / "SecureCredentialStore.kt").read_text(encoding="utf-8")
CLIENT = (ANDROID / "app" / "src" / "main" / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "DesktopApiClient.kt").read_text(encoding="utf-8")
GRADLE = (ANDROID / "app" / "build.gradle.kts").read_text(encoding="utf-8")


def test_android_app_disables_cleartext_and_platform_backups():
    assert 'android:usesCleartextTraffic="false"' in MANIFEST
    assert 'android:allowBackup="false"' in MANIFEST
    assert 'android.permission.INTERNET' in MANIFEST


def test_device_credentials_use_android_keystore_aes_gcm():
    assert 'AndroidKeyStore' in STORE
    assert 'AES/GCM/NoPadding' in STORE
    assert 'KeyProperties.KEY_ALGORITHM_AES' in STORE
    assert '.putString(KEY_LOCAL_TOKEN, encrypt(token))' in STORE
    assert '.putString(KEY_REMOTE_TOKEN, encrypt(gatewayToken))' in STORE
    assert '.putString(KEY_LOCAL_TOKEN, token)' not in STORE
    assert '.putString(KEY_REMOTE_TOKEN, gatewayToken)' not in STORE


def test_mobile_endpoint_and_api_client_are_https_only():
    assert 'validateHttpsEndpoint(baseUrl)' in STORE
    assert 'uri.scheme.equals("https", ignoreCase = true)' in STORE
    assert 'baseUri.scheme.equals("https", true)' in CLIENT
    assert 'instanceFollowRedirects = false' in CLIENT
    assert 'X-DPN-Token' in CLIENT
    assert 'X-DPN-Device-ID' in CLIENT


def test_release_build_enables_minification_without_debug_release():
    assert 'isMinifyEnabled = true' in GRADLE
    release = GRADLE.split('release {', 1)[1]
    assert 'isDebuggable = true' not in release


def test_mobile_does_not_embed_desktop_credentials():
    combined = STORE + CLIENT + GRADLE + MANIFEST
    forbidden = ('DPN_ACCESS_TOKEN=', 'sk-', 'BEGIN PRIVATE KEY', 'password=')
    assert not any(marker in combined for marker in forbidden)
