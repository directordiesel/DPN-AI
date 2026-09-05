from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android" / "app" / "src" / "main"
VOICE = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "VoiceActivity.kt").read_text(encoding="utf-8")
MAIN = (ANDROID / "java" / "com" / "dpntechnology" / "dpnai" / "MainActivity.kt").read_text(encoding="utf-8")
MANIFEST = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")


def test_voice_is_explicit_tap_to_talk_not_background_capture():
    assert 'Tap to Talk' in VOICE
    assert 'requestMicrophoneAndListen()' in VOICE
    assert 'speechRecognizer.startListening(intent)' in VOICE
    assert 'speechRecognizer.stopListening()' in VOICE
    assert 'SpeechRecognizer.createSpeechRecognizer' in VOICE
    assert 'Service' not in VOICE
    assert 'FOREGROUND_SERVICE_MICROPHONE' not in MANIFEST


def test_microphone_permission_is_runtime_gated():
    assert 'android.permission.RECORD_AUDIO' in MANIFEST
    assert 'checkSelfPermission(Manifest.permission.RECORD_AUDIO)' in VOICE
    assert 'requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO)' in VOICE
    assert 'Microphone permission denied — voice capture remains off.' in VOICE


def test_voice_request_uses_unified_ai_chat_runtime():
    assert 'api.sendChat(' in VOICE
    assert 'profile = "auto"' in VOICE
    assert 'executionMode = "auto"' in VOICE
    assert 'Voice reply synchronized with DPN AI conversation' in VOICE


def test_voice_output_is_bounded_and_stoppable():
    assert 'MAX_SPEAK_CHARS' in VOICE
    assert 'TextToSpeech.QUEUE_FLUSH' in VOICE
    assert 'Stop Speaking' in VOICE
    assert 'tts.stop()' in VOICE
    assert 'tts.shutdown()' in VOICE


def test_voice_activity_is_pairing_gated_and_not_exported():
    assert 'addCapability(root, "Voice Console", VoiceActivity::class.java)' in MAIN
    assert 'setCapabilityButtons(active)' in MAIN
    assert 'capabilityButtons.forEach { it.isEnabled = enabled }' in MAIN
    assert 'android:name=".VoiceActivity"' in MANIFEST
    voice_section = MANIFEST.split('android:name=".VoiceActivity"', 1)[1].split('/>', 1)[0]
    assert 'android:exported="false"' in voice_section


def test_voice_code_does_not_add_androidx_dependency_requirement():
    assert 'androidx.' not in VOICE
