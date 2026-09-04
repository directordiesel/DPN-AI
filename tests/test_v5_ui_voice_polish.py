from pathlib import Path

from app.voice_adapter import VOICE_PROFILES, VoiceAdapter

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CSS = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")


def test_every_control_center_surface_is_bounded_and_scrollable():
    assert "max-height: calc(var(--dpn-viewport-height) - 28px)" in CSS
    assert "scrollbar-gutter: stable both-edges" in CSS
    assert ".file-table, .audit-list, .kanban" in CSS
    assert "grid-template-columns: repeat(auto-fit" in CSS
    assert "@media (max-height: 780px)" in CSS


def test_ui_cache_and_missing_shell_recovery_are_present():
    assert "validateInterfaceShell" in JS
    assert "Repair cached interface" in JS
    assert f"navigator.serviceWorker.register('/sw.js?v={VERSION}')" in JS
    assert f"/styles.css?v={VERSION}" in HTML


def test_sentinel_uses_hd_primary_with_legacy_fallback_and_natural_pace():
    profile = VOICE_PROFILES["sentinel"]
    assert profile["model"] == "en_US-ryan-high"
    assert "en_GB-alan-medium" in profile["fallback_models"]
    assert 0.88 <= profile["default_speed"] <= 0.96
    assert profile["compression_ratio"] < 1.8
    assert profile["max_makeup_gain"] <= 1.03


def test_voice_tone_profile_is_selectable(tmp_path):
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")
    clear = adapter._tone_profile(VOICE_PROFILES["sentinel"], "clear")
    warm = adapter._tone_profile(VOICE_PROFILES["sentinel"], "warm")
    assert clear["active_tone"] == "clear"
    assert warm["active_tone"] == "warm"
    assert clear["high_cut_hz"] > warm["high_cut_hz"]


def test_browser_sends_selected_voice_tone():
    assert "tone:voiceToneFor(voiceId)" in JS
    assert "data-voice-tone" in JS


def test_stale_message_template_is_repaired_instead_of_crashing():
    assert "function ensureMessagePart" in JS
    assert "if (!actions) return" in JS
    assert "const streamNode = ensureMessagePart" in JS