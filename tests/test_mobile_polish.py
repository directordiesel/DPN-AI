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
    assert "loadRemoteCredential" in DIAG
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
