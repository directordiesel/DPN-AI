from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

from app.voice_adapter import VOICE_PROFILES, VoiceAdapter


def test_voice_profiles_have_distinct_narration_presets(tmp_path: Path):
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")
    profiles = {item["id"]: item for item in adapter.profiles()["profiles"]}
    sentinel = profiles["sentinel"]
    aurora = profiles["aurora"]
    assert sentinel["default_speed"] < 0.9
    assert aurora["default_speed"] < sentinel["default_speed"]
    assert aurora["sentence_pause_ms"] > sentinel["sentence_pause_ms"]
    assert aurora["target_peak"] < sentinel["target_peak"]
    assert aurora["noise_scale"] < sentinel["noise_scale"]
    assert "gentle" in aurora["style"].lower()
    assert sentinel["tone"] != aurora["tone"]


def test_narration_units_add_sentence_and_paragraph_breathing_room():
    text = "First sentence. Second sentence.\n\nA new paragraph begins here."
    units = VoiceAdapter._narration_units(text, VOICE_PROFILES["aurora"])
    assert [unit for unit, _ in units] == ["First sentence.", "Second sentence.", "A new paragraph begins here."]
    assert units[0][1] == VOICE_PROFILES["aurora"]["sentence_pause_ms"]
    assert units[1][1] == VOICE_PROFILES["aurora"]["paragraph_pause_ms"]
    assert units[-1][1] > 0


def test_long_phrases_are_split_without_losing_words():
    text = ", ".join([f"item {index}" for index in range(80)]) + "."
    units = VoiceAdapter._narration_units(text, VOICE_PROFILES["sentinel"])
    joined = " ".join(unit for unit, _ in units)
    assert len(units) > 1
    assert "item 0" in joined and "item 79" in joined
    assert all(len(unit) <= 300 for unit, _ in units)


def test_aurora_pcm_processing_reduces_harsh_peaks():
    sample_rate = 22050
    source = array("h")
    for index in range(sample_rate // 4):
        # Deliberately harsh near-Nyquist alternating waveform with sharp peaks.
        value = 31000 if index % 2 == 0 else -31000
        source.append(value)
    raw = source.tobytes()
    softened = VoiceAdapter._soften_pcm16(raw, sample_rate, 1, VOICE_PROFILES["aurora"])
    result = array("h")
    result.frombytes(softened)
    assert len(result) == len(source)
    assert max(abs(value) for value in result) < max(abs(value) for value in source)
    source_delta = sum(abs(source[i] - source[i - 1]) for i in range(1, len(source)))
    result_delta = sum(abs(result[i] - result[i - 1]) for i in range(1, len(result)))
    assert result_delta < source_delta


def test_speak_uses_profile_natural_speed_and_reports_delivery(tmp_path: Path, monkeypatch):
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")

    def fake_speak(text, target, profile, speed, volume, use_cuda):
        with wave.open(str(target), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            samples = array("h", [int(8000 * math.sin(index / 20)) for index in range(1600)])
            wav_file.writeframes(samples.tobytes())
        return {"segments": 2, "inserted_pause_ms": 390, "processing": "test narration"}

    monkeypatch.setattr(adapter, "_speak_piper", fake_speak)
    result = adapter.speak("Hello. This is a gentle test.", voice_id="aurora", fallback=False)
    assert result["ok"] is True
    assert result["speed"] == VOICE_PROFILES["aurora"]["default_speed"]
    assert result["delivery"]["segments"] == 2
    assert result["delivery"]["inserted_pause_ms"] == 390
    assert (tmp_path / "workspace" / result["path"]).exists()


def test_voice_ui_sends_profile_speed_and_exposes_natural_pace_control():
    app_js = Path("app/static/app.js").read_text(encoding="utf-8")
    assert "voiceSpeedFor(voiceId)" in app_js
    assert "speed, filename" in app_js
    assert "data-voice-speed" in app_js
    assert "Natural Pace" in app_js
    assert "Take a comfortable breath" in app_js


def test_segmented_piper_pipeline_writes_real_pause_frames(tmp_path: Path, monkeypatch):
    import sys
    import types

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeVoice:
        def synthesize_wav(self, text, wav_file, syn_config=None):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(1000)
            # 100 ms of deliberately sharp audio per narration unit.
            value = 24000 if len(text) % 2 else -24000
            wav_file.writeframes(array("h", [value if i % 2 else -value for i in range(100)]).tobytes())

    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(SynthesisConfig=FakeConfig))
    adapter = VoiceAdapter(tmp_path / "workspace", tmp_path / "data")
    model = VOICE_PROFILES["aurora"]["model"]
    (tmp_path / "data" / "voices" / f"{model}.onnx").write_bytes(b"model")
    (tmp_path / "data" / "voices" / f"{model}.onnx.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(adapter, "_load_piper", lambda model, use_cuda=False: FakeVoice())
    target = tmp_path / "workspace" / "generated" / "voice" / "segmented.wav"
    delivery = adapter._speak_piper("One sentence. Two sentence.", target, VOICE_PROFILES["aurora"], 0.76, 1.0, False)
    with wave.open(str(target), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
    # 200 ms speech plus at least one 390 ms Aurora sentence pause.
    assert frame_count / sample_rate >= 0.59
    assert delivery["segments"] == 2
    assert delivery["inserted_pause_ms"] >= VOICE_PROFILES["aurora"]["sentence_pause_ms"]