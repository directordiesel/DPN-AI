from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.voice_adapter import VoiceAdapter
from app.voice_security import VoiceSecurityGuard, install_voice_security


class _Registered:
    def __init__(self, function):
        self.function = function


def _voice(tmp_path: Path) -> VoiceAdapter:
    return VoiceAdapter(tmp_path / "workspace", tmp_path / "data")


def test_voice_transcription_rejects_unapproved_model_before_engine_load(tmp_path: Path):
    voice = _voice(tmp_path)
    guard = VoiceSecurityGuard(voice)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("transcription engine should not run")

    guard._original_transcribe = fail_if_called
    result = guard.transcribe("missing.wav", model_size="../../remote-model")

    assert result["ok"] is False
    assert "allow-listed" in result["error"]
    assert called is False


def test_voice_transcription_rejects_symlinked_audio_source(tmp_path: Path):
    voice = _voice(tmp_path)
    guard = VoiceSecurityGuard(voice)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"RIFF" + b"0" * 64)
    linked = voice.workspace / "linked.wav"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")

    result = guard.transcribe("linked.wav")

    assert result["ok"] is False
    assert "symlink" in result["error"].lower()


def test_voice_upload_has_hard_size_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    voice = _voice(tmp_path)
    guard = VoiceSecurityGuard(voice)
    monkeypatch.setattr("app.voice_security.MAX_UPLOAD_BYTES", 16)

    with pytest.raises(ValueError, match="exceeds"):
        guard.save_upload(b"x" * 17, "capture.webm")

    assert list(voice.upload_dir.iterdir()) == []


def test_voice_model_download_uses_minimal_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    voice = _voice(tmp_path)
    guard = VoiceSecurityGuard(voice)
    monkeypatch.setenv("DPN_TEST_API_KEY", "must-not-reach-downloader")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setattr(voice, "_module_available", lambda name: name == "piper")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured.update(kwargs)
        model = voice.voice_dir / "en_US-ryan-high.onnx"
        model.write_bytes(b"model")
        model.with_suffix(".onnx.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="downloaded", stderr="")

    monkeypatch.setattr("app.voice_security.subprocess.run", fake_run)
    result = guard.install_profile("sentinel")

    assert result["ok"] is True
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["env"].get("DPN_TEST_API_KEY") is None
    assert captured["command"][1:3] == ["-m", "piper.download_voices"]
    assert captured["command"][-1] == "en_US-ryan-high"
    assert captured["cwd"] == str(voice.voice_dir)


def test_voice_speech_publishes_atomically_to_final_name(tmp_path: Path):
    voice = _voice(tmp_path)
    guard = VoiceSecurityGuard(voice)

    def fake_speak(*, text, filename, **kwargs):
        temp = voice.output_dir / filename
        temp.write_bytes(b"RIFF" + b"0" * 80)
        return {"ok": True, "path": temp.relative_to(voice.workspace).as_posix(), "size_bytes": temp.stat().st_size}

    guard._original_speak = fake_speak
    result = guard.speak("hello", filename="final.wav")

    assert result["ok"] is True
    assert result["path"] == "generated/voice/final.wav"
    assert (voice.output_dir / "final.wav").is_file()
    assert not list(voice.output_dir.glob(".dpn-voice-*.wav"))


def test_voice_speech_refuses_symlinked_final_target(tmp_path: Path):
    voice = _voice(tmp_path)
    guard = VoiceSecurityGuard(voice)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside")
    linked = voice.output_dir / "final.wav"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")

    result = guard.speak("hello", filename="final.wav")

    assert result["ok"] is False
    assert "symlink" in result["error"].lower()
    assert outside.read_bytes() == b"outside"


def test_core_install_rewires_registered_voice_callbacks(tmp_path: Path):
    voice = _voice(tmp_path)
    registry = SimpleNamespace(
        voice=voice,
        tools={
            "install_voice_profile": _Registered(voice.install_profile),
            "transcribe_audio": _Registered(voice.transcribe),
            "speak_text": _Registered(voice.speak),
        },
    )

    guard = install_voice_security(registry)

    assert guard is registry.voice_security
    assert registry.tools["install_voice_profile"].function == guard.install_profile
    assert registry.tools["transcribe_audio"].function == guard.transcribe
    assert registry.tools["speak_text"].function == guard.speak
    assert voice.save_upload == guard.save_upload
