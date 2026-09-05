from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android" / "app" / "src" / "main"


def test_file_console_is_internal_and_pairing_gated():
    manifest = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")
    main = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "MainActivity.kt").read_text(encoding="utf-8")
    assert 'android:name=".FileActivity"' in manifest
    file_decl = manifest.split('android:name=".FileActivity"', 1)[1].split("/>", 1)[0]
    assert 'android:exported="false"' in file_decl
    assert 'addCapability(root, "File Intelligence", FileActivity::class.java)' in main
    assert 'setCapabilityButtons(active)' in main
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in main


def test_file_picker_requires_explicit_user_selection_and_bounds_reads():
    activity = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "FileActivity.kt").read_text(encoding="utf-8")
    assert "Intent.ACTION_OPEN_DOCUMENT" in activity
    assert "Intent.CATEGORY_OPENABLE" in activity
    assert "MAX_FILE_BYTES = 50 * 1024 * 1024" in activity
    assert "require(total <= MAX_FILE_BYTES)" in activity
    assert "startActivityForResult(intent, REQUEST_FILE)" in activity


def test_general_upload_reuses_authenticated_https_api_and_blocks_executable_packages():
    client = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "DesktopApiClient.kt").read_text(encoding="utf-8")
    assert 'fun uploadFile(bytes: ByteArray, filename: String, mimeType: String)' in client
    assert 'openConnection("POST", "/api/files/upload")' in client
    assert 'setRequestProperty("X-DPN-Token", credential.token)' in client
    assert 'setRequestProperty("X-DPN-Device-ID", credential.deviceId)' in client
    assert 'baseUri.scheme.equals("https", true)' in client
    assert 'instanceFollowRedirects = false' in client
    assert '"application/vnd.android.package-archive"' in client
    assert '"application/x-msdownload"' in client


def test_file_analysis_uses_unified_chat_attachment_path():
    activity = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "FileActivity.kt").read_text(encoding="utf-8")
    client = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "DesktopApiClient.kt").read_text(encoding="utf-8")
    assert "api.uploadFile(bytes, name, mime)" in activity
    assert "api.sendChat(" in activity
    assert "attachments = listOf(upload.workspacePath)" in activity
    assert 'require(!workspacePath.startsWith("/") && !workspacePath.contains(".."))' in client
    assert 'clean.isNotEmpty() && clean.length <= 1000' in client
    assert '!clean.startsWith("/") && !clean.contains("..")' in client
