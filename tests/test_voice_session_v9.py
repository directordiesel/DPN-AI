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


def test_interrupt_is_fail_closed_when_not_speaking(tmp_path: Path):
    runtime = VoiceSessionRuntime(tmp_path)
    result = runtime.interrupt()
    assert result == {"ok": False, "interrupted": False, "state": "idle"}


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
