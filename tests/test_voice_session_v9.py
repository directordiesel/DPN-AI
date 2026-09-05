from pathlib import Path

import pytest

from app.voice_session_v9 import MultimodalAttachment, VoiceSessionRuntime


def test_hands_free_session_returns_to_listening(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path, hands_free=True)
    assert runtime.start()["state"] == "listening"
    turn = runtime.begin_turn("What is the system status?")
    assert turn["state"] == "thinking"
    runtime.begin_speaking()
    completed = runtime.complete_turn()
    assert completed["next_state"] == "listening"


def test_barge_in_interrupts_active_speech(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    runtime.start()
    runtime.begin_turn("Read the report")
    runtime.begin_speaking()
    result = runtime.interrupt()
    assert result["ok"] is True
    assert result["interrupted"] is True
    assert result["state"] == "interrupted"
    assert result["turn"]["interrupted"] is True
    assert result["turn"]["interruption_reason"] == "barge_in"
    assert runtime.status()["interruption_count"] == 1


def test_interrupt_is_fail_closed_when_not_speaking(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    result = runtime.interrupt()
    assert result == {"ok": False, "interrupted": False, "state": "idle"}


def test_interrupted_turn_must_be_abandoned_before_next_turn(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path, hands_free=True)
    runtime.start()
    runtime.begin_turn("Read the report")
    runtime.begin_speaking()
    runtime.interrupt("user_started_speaking")
    with pytest.raises(ValueError, match="already active"):
        runtime.begin_turn("New request")
    with pytest.raises(ValueError, match="must be abandoned"):
        runtime.complete_turn()
    result = runtime.abandon_interrupted_turn()
    assert result["abandoned"] is True
    assert result["next_state"] == "listening"
    assert runtime.begin_turn("New request")["state"] == "thinking"


def test_begin_speaking_requires_thinking_state(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    runtime.begin_turn("Answer me")
    runtime.begin_speaking()
    with pytest.raises(ValueError, match="Cannot begin speaking"):
        runtime.begin_speaking()


def test_stop_invalidates_active_turn_and_requires_restart(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    runtime.start()
    runtime.begin_turn("Still there?")
    stopped = runtime.stop()
    assert stopped["state"] == "stopped"
    assert stopped["active_turn_id"] is None
    with pytest.raises(ValueError, match="session is stopped"):
        runtime.begin_turn("Try again")
    assert runtime.start()["state"] == "listening"
    assert runtime.begin_turn("Try again")["state"] == "thinking"


def test_restart_rejected_while_turn_is_active(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    runtime.start()
    runtime.begin_turn("Busy")
    with pytest.raises(ValueError, match="while a turn is active"):
        runtime.start()


def test_voice_turn_source_is_bounded(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    result = runtime.begin_turn("From mic", source="microphone")
    assert result["turn"]["source"] == "microphone"
    runtime.complete_turn()
    with pytest.raises(ValueError, match="Unsupported voice turn source"):
        runtime.begin_turn("Bad source", source="arbitrary-provider")


def test_status_is_honest_about_microphone_provider(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    status = runtime.status()
    assert status["live_microphone_capture"] is False
    assert "No trusted platform microphone" in status["live_microphone_reason"]


def test_multimodal_turn_tracks_modalities(tmp_path: Path):
    (tmp_path / "screen.png").write_bytes(b"image")
    (tmp_path / "note.md").write_text("hello", encoding="utf-8")
    runtime = VoiceSessionRuntime(tmp_path)
    result = runtime.begin_turn(
        "Explain these files",
        attachments=[
            MultimodalAttachment("screen.png", "image"),
            MultimodalAttachment("note.md", "document"),
        ],
    )
    assert result["turn"]["modalities"] == ["document", "image", "text"]
    assert result["turn"]["attachments"][0]["path"] == "screen.png"


def test_attachment_must_stay_in_workspace_and_match_type(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        runtime.begin_turn("Inspect", [MultimodalAttachment("../outside.png", "image")])

    bad = tmp_path / "bad.txt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported image"):
        runtime.begin_turn("Inspect", [MultimodalAttachment("bad.txt", "image")])


def test_attachment_count_is_bounded(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    attachments = []
    for index in range(9):
        path = tmp_path / f"{index}.png"
        path.write_bytes(b"x")
        attachments.append(MultimodalAttachment(path.name, "image"))
    with pytest.raises(ValueError, match="at most 8"):
        runtime.begin_turn("Inspect", attachments)
