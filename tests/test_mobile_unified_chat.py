from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android" / "app" / "src" / "main"
CLIENT = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "network" / "DesktopApiClient.kt").read_text(encoding="utf-8")
CHAT = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "ChatActivity.kt").read_text(encoding="utf-8")
MAIN = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "MainActivity.kt").read_text(encoding="utf-8")
MANIFEST = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")


def test_mobile_chat_uses_unified_backend_conversation_contract():
    assert '"/api/conversations"' in CLIENT
    assert '"/api/conversations/$safeId"' in CLIENT
    assert '"/api/chat"' in CLIENT
    assert '"conversation_id"' in CLIENT
    assert '"project_id"' in CLIENT
    assert '"execution_mode"' in CLIENT


def test_mobile_chat_preserves_device_authentication_and_https_boundary():
    assert 'baseUri.scheme.equals("https"' in CLIENT
    assert 'X-DPN-Token' in CLIENT
    assert 'X-DPN-Device-ID' in CLIENT
    assert 'instanceFollowRedirects = false' in CLIENT
    assert 'path.startsWith("/api/")' in CLIENT
    assert 'MAX_RESPONSE_CHARS' in CLIENT


def test_chat_activity_syncs_server_history_instead_of_mobile_only_history():
    assert 'api.listConversations()' in CHAT
    assert 'api.getConversation(conversationId)' in CHAT
    assert 'api.createConversation(' in CHAT
    assert 'api.sendChat(' in CHAT
    assert 'activeConversationId' in CHAT
    assert 'Shared conversations with the desktop AI runtime' in CHAT


def test_control_center_exposes_chat_only_after_pairing():
    assert 'Open Unified Chat' in MAIN
    assert 'chatButton.isEnabled = paired' in MAIN
    assert 'ChatActivity::class.java' in MAIN


def test_chat_activity_is_not_exported_to_other_apps():
    assert 'android:name=".ChatActivity"' in MANIFEST
    chat_section = MANIFEST.split('android:name=".ChatActivity"', 1)[1].split('/>', 1)[0]
    assert 'android:exported="false"' in chat_section
