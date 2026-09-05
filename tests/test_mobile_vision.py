from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android" / "app" / "src" / "main"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_vision_activity_is_internal_and_control_center_gated():
    manifest = read(ANDROID / "AndroidManifest.xml")
    main = read(ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "MainActivity.kt")
    assert 'android:name=".VisionActivity"' in manifest
    vision_registration = manifest.split('android:name=".VisionActivity"', 1)[1].split("/>", 1)[0]
    assert 'android:exported="false"' in vision_registration
    assert 'addCapability(root, "Vision Console", VisionActivity::class.java)' in main
    assert 'setCapabilityButtons(active)' in main
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in main


def test_camera_and_gallery_are_explicit_user_actions_without_background_capture():
    source = read(ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "VisionActivity.kt")
    assert "MediaStore.ACTION_IMAGE_CAPTURE" in source
    assert "Intent.ACTION_OPEN_DOCUMENT" in source
    assert 'text = "Take Photo"' in source
    assert 'text = "Choose Image"' in source
    assert "Service" not in source
    assert "CameraManager" not in source


def test_mobile_vision_uses_bounded_authenticated_workspace_upload_and_unified_chat():
    api = read(ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "DesktopApiClient.kt")
    vision = read(ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "VisionActivity.kt")
    assert 'openConnection("POST", "/api/files/upload")' in api
    assert 'setRequestProperty("X-DPN-Token", credential.token)' in api
    assert 'setRequestProperty("X-DPN-Device-ID", credential.deviceId)' in api
    assert "MAX_IMAGE_BYTES = 20 * 1024 * 1024" in api
    assert 'setOf("image/jpeg", "image/png", "image/webp")' in api
    assert "attachments = listOf(upload.workspacePath)" in vision
    assert "api.sendChat(" in vision
    assert 'put("attachments", JSONArray(safeAttachments))' in api


def test_attachment_paths_are_workspace_relative_and_bounded():
    api = read(ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "DesktopApiClient.kt")
    assert 'clean.isNotEmpty() && clean.length <= 1000' in api
    assert '!clean.startsWith("/") && !clean.contains("..")' in api
    assert "MAX_ATTACHMENTS = 8" in api
    assert "MAX_RESPONSE_CHARS = 2_000_000" in api
