from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/MainActivity.kt").read_text(encoding="utf-8")
DIAG = (ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/DiagnosticsActivity.kt").read_text(encoding="utf-8")
STORE = (ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai/diagnostics/MobileDiagnostics.kt").read_text(encoding="utf-8")
MANIFEST = (ROOT / "mobile/android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")


def test_control_center_is_scrollable_and_sectioned():
    assert "ScrollView" in MAIN
    assert 'addSection(root, "ASSIST")' in MAIN
    assert 'addSection(root, "OPERATE")' in MAIN
    assert 'addSection(root, "SYSTEM")' in MAIN


def test_control_center_displays_version_and_diagnostics_entry():
    assert "BuildConfig.VERSION_NAME" in MAIN
    assert "Diagnostics & Status" in MAIN
    assert "DiagnosticsActivity::class.java" in MAIN


def test_diagnostics_activity_is_internal_only():
    assert '<activity android:name=".DiagnosticsActivity" android:exported="false" />' in MANIFEST


def test_diagnostics_exposes_build_connection_and_security_state_without_tokens():
    assert "BuildConfig.VERSION_NAME" in DIAG
    assert "BuildConfig.VERSION_CODE" in DIAG
    assert "BuildConfig.BUILD_TYPE" in DIAG
    assert "loadLocalCredential" in DIAG
    assert "hasRemoteGateway" in DIAG
    assert "loadDesktopCredential" in DIAG
    assert "Android Keystore AES/GCM" in DIAG
    assert "credential.token" not in DIAG
    assert "X-DPN-Token" not in DIAG


def test_error_store_is_bounded_and_redacts_common_secret_labels():
    assert "MAX_ERROR_CHARS = 2000" in STORE
    assert "<redacted>" in STORE
    for label in ("token", "password", "secret", "authorization", "x-dpn-token"):
        assert label in STORE.lower()


def test_diagnostics_has_no_external_reporting_or_background_worker():
    combined = DIAG + STORE
    for forbidden in ("WorkManager", "JobService", "AlarmManager", "FirebaseCrashlytics", "Sentry"):
        assert forbidden not in combined



ANDROID_UI = ROOT / "mobile/android/app/src/main/java/com/dpntechnology/dpnai"
PRIMARY_ACTIVITIES = (
    "MainActivity.kt",
    "GatewayActivity.kt",
    "ChatActivity.kt",
    "ApprovalsActivity.kt",
    "MissionsActivity.kt",
    "ProjectsActivity.kt",
    "FileActivity.kt",
    "VoiceActivity.kt",
    "VisionActivity.kt",
    "NotificationsActivity.kt",
    "DiagnosticsActivity.kt",
)


def test_every_primary_android_screen_is_scrollable():
    missing = []
    for name in PRIMARY_ACTIVITIES:
        text = (ANDROID_UI / name).read_text(encoding="utf-8")
        if "ScrollView" not in text:
            missing.append(name)
    assert missing == []


def test_primary_android_ui_copy_is_plain_ascii():
    failures = {}
    for name in PRIMARY_ACTIVITIES:
        text = (ANDROID_UI / name).read_text(encoding="utf-8")
        chars = sorted({char for char in text if ord(char) > 127})
        if chars:
            failures[name] = chars
    assert failures == {}


def test_programmatic_android_buttons_have_click_handlers():
    failures = {}
    for name in PRIMARY_ACTIVITIES:
        text = (ANDROID_UI / name).read_text(encoding="utf-8")
        buttons = text.count("Button(")
        handlers = text.count("setOnClickListener")
        if handlers < buttons:
            failures[name] = {"buttons": buttons, "handlers": handlers}
    assert failures == {}



def test_mobile_connection_failures_direct_users_to_safe_diagnostics():
    main = (ANDROID_UI / "MainActivity.kt").read_text(encoding="utf-8")
    gateway = (ANDROID_UI / "GatewayActivity.kt").read_text(encoding="utf-8")

    assert "Make sure DPN AI is running and this device is paired, then retry." in main
    assert "Open Diagnostics & Status for technical details." in main
    assert "Connection unavailable - ${it.message" not in main

    assert 'MobileDiagnostics.recordError(this, "gateway-save", it)' in gateway
    assert 'MobileDiagnostics.recordError(this, "gateway-mode", it)' in gateway
    assert 'MobileDiagnostics.recordError(this, "gateway-test", it)' in gateway
    assert "Technical details are available in Diagnostics & Status." in gateway
    assert "Gateway rejected: ${it.message}" not in gateway
    assert "Mode switch failed: ${it.message}" not in gateway
    assert "Connection test failed: ${it.message}" not in gateway


def test_mobile_voice_unavailability_has_a_recovery_path():
    voice = (ANDROID_UI / "VoiceActivity.kt").read_text(encoding="utf-8")

    assert "Speech recognition is not available on this device." in voice
    assert "Use Unified Chat" in voice
    assert "enable/install a supported Android speech service" in voice


def test_gateway_credential_entry_is_private_and_not_restored():
    gateway = (ANDROID_UI / "GatewayActivity.kt").read_text(encoding="utf-8")

    assert "WindowManager.LayoutParams.FLAG_SECURE" in gateway
    assert "InputType.TYPE_TEXT_VARIATION_PASSWORD" in gateway
    assert "View.IMPORTANT_FOR_AUTOFILL_NO" in gateway
    assert "isSaveEnabled = false" in gateway
    assert "setSingleLine(true)" in gateway


def test_mobile_diagnostics_redact_bearer_and_api_key_credentials():
    assert 'Regex("(?i)\\\\bBearer\\\\s+' in STORE
    assert "Bearer <redacted>" in STORE
    assert "api[-_]?key" in STORE
