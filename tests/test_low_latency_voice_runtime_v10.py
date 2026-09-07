from __future__ import annotations

import asyncio
import threading

import pytest

from app.low_latency_voice_runtime_v10 import (
    LowLatencyVoiceRuntime,
    VoiceRuntimeError,
    VoiceRuntimePolicy,
)
from app.voice_session_v9 import VoiceSessionRuntime, VoiceSessionState


class FakeVoiceAdapter:
    def __init__(self) -> None:
        self.speak_calls: list[tuple] = []
        self.transcribe_calls: list[tuple] = []
        self.block_speak = False
        self.block_transcribe = False
        self.fail_speak = False
        self.speak_started = threading.Event()
        self.speak_release = threading.Event()
        self.transcribe_started = threading.Event()
        self.transcribe_release = threading.Event()

    def speak(self, text, filename, rate, voice_id, speed, volume, use_cuda, fallback, tone):
        self.speak_calls.append((text, filename, rate, voice_id, speed, volume, use_cuda, fallback, tone))
        if self.block_speak:
            self.speak_started.set()
            self.speak_release.wait(timeout=2)
        if self.fail_speak:
            return {"ok": False, "error": "synthetic failure"}
        return {
            "ok": True,
            "path": f"generated/voice/{filename}",
            "engine": "fake",
            "elapsed_ms": 12,
        }

    def transcribe(self, path, model_size, language, initial_prompt, device, compute_type):
        self.transcribe_calls.append((path, model_size, language, initial_prompt, device, compute_type))
        if self.block_transcribe:
            self.transcribe_started.set()
            self.transcribe_release.wait(timeout=2)
        return {
            "ok": True,
            "path": path,
            "text": "verified transcript",
            "segments": [{"start": 0.0, "end": 1.0, "text": "verified transcript"}],
            "language": language or "en",
            "model": model_size,
            "elapsed_ms": 20,
        }


def _runtime(tmp_path, *, adapter=None, hands_free=True, policy=None):
    session = VoiceSessionRuntime(tmp_path, hands_free=hands_free)
    session.start(hands_free=hands_free)
    voice = adapter or FakeVoiceAdapter()
    return voice, session, LowLatencyVoiceRuntime(voice, session, policy=policy)


def test_voice_runtime_chunks_response_and_reports_first_audio_latency(tmp_path):
    adapter, session, runtime = _runtime(
        tmp_path,
        policy=VoiceRuntimePolicy(max_chunk_characters=80, target_first_audio_ms=1500),
    )
    turn = session.begin_turn("User request")

    result = asyncio.run(
        runtime.synthesize_active_turn(
            "First sentence is intentionally long enough to create bounded delivery. Second sentence follows immediately."
        )
    )

    assert result.ok is True
    assert result.turn_id == turn["turn"]["turn_id"]
    assert result.interrupted is False
    assert result.stale is False
    assert result.chunks_requested >= 2
    assert result.chunks_completed == result.chunks_requested
    assert len(adapter.speak_calls) == result.chunks_completed
    assert result.first_audio_ms is not None
    assert result.latency_target_met is True
    assert all(item["path"].startswith("generated/voice/v10-") for item in result.audio)
    assert session.state == VoiceSessionState.LISTENING
    assert session.active_turn is None


def test_voice_runtime_barge_in_reuses_session_authority_and_stops_at_safe_boundary(tmp_path):
    async def scenario():
        adapter = FakeVoiceAdapter()
        adapter.block_speak = True
        adapter, session, runtime = _runtime(
            tmp_path,
            adapter=adapter,
            policy=VoiceRuntimePolicy(max_chunk_characters=70),
        )
        session.begin_turn("User request")
        task = asyncio.create_task(
            runtime.synthesize_active_turn(
                "This first chunk is deliberately long enough to enter synthesis. This second chunk must never be synthesized after interruption."
            )
        )
        assert await asyncio.to_thread(adapter.speak_started.wait, 1.0)
        interrupted = runtime.interrupt("user_barge_in")
        adapter.speak_release.set()
        result = await task
        return adapter, session, interrupted, result

    adapter, session, interrupted, result = asyncio.run(scenario())
    assert interrupted["ok"] is True
    assert interrupted["interrupted"] is True
    assert result.ok is False
    assert result.interrupted is True
    assert result.stale is True
    assert result.chunks_completed == 0
    assert len(adapter.speak_calls) == 1
    assert session.state == VoiceSessionState.INTERRUPTED
    assert session.active_turn is not None
    assert session.active_turn.interruption_reason == "user_barge_in"


def test_voice_runtime_discards_transcription_after_session_stop(tmp_path):
    async def scenario():
        adapter = FakeVoiceAdapter()
        adapter.block_transcribe = True
        adapter, session, runtime = _runtime(tmp_path, adapter=adapter)
        task = asyncio.create_task(runtime.transcribe_audio("uploads/voice/input.wav"))
        assert await asyncio.to_thread(adapter.transcribe_started.wait, 1.0)
        session.stop()
        adapter.transcribe_release.set()
        return await task

    result = asyncio.run(scenario())
    assert result.ok is False
    assert result.interrupted is True
    assert result.stale is True
    assert result.transcript is None


def test_new_voice_turn_uses_existing_hands_free_lifecycle(tmp_path):
    adapter, session, runtime = _runtime(tmp_path, hands_free=True)

    first_turn = session.begin_turn("First user turn")["turn"]["turn_id"]
    first = asyncio.run(runtime.synthesize_active_turn("Short response."))
    second_turn = session.begin_turn("Second user turn")["turn"]["turn_id"]
    second = asyncio.run(runtime.synthesize_active_turn("Another short response."))

    assert first.ok is True
    assert second.ok is True
    assert first.turn_id == first_turn
    assert second.turn_id == second_turn
    assert first.turn_id != second.turn_id
    assert session.turn_index == 2
    assert session.state == VoiceSessionState.LISTENING


def test_voice_runtime_fails_closed_before_adapter_call_for_oversized_response(tmp_path):
    adapter, session, runtime = _runtime(
        tmp_path,
        policy=VoiceRuntimePolicy(max_input_characters=256),
    )
    session.begin_turn("User request")

    with pytest.raises(VoiceRuntimeError, match="input bound"):
        asyncio.run(runtime.synthesize_active_turn("x" * 257))

    assert adapter.speak_calls == []
    assert session.state == VoiceSessionState.THINKING


def test_synthesis_failure_moves_existing_turn_to_interrupted_fail_closed_state(tmp_path):
    adapter = FakeVoiceAdapter()
    adapter.fail_speak = True
    adapter, session, runtime = _runtime(tmp_path, adapter=adapter)
    session.begin_turn("User request")

    result = asyncio.run(runtime.synthesize_active_turn("This synthesis will fail."))

    assert result.ok is False
    assert result.error == "synthetic failure"
    assert session.state == VoiceSessionState.INTERRUPTED
    assert session.active_turn is not None
    assert session.active_turn.interruption_reason == "synthesis_failed"


def test_voice_policy_rejects_unsafe_chunk_configuration(tmp_path):
    adapter, session, _ = _runtime(tmp_path)
    with pytest.raises(VoiceRuntimeError, match="max_chunk_characters"):
        LowLatencyVoiceRuntime(adapter, session, policy=VoiceRuntimePolicy(max_chunk_characters=10))


def test_voice_runtime_status_exposes_shared_session_and_latency_policy(tmp_path):
    _, session, runtime = _runtime(tmp_path)
    status = runtime.status()

    assert status["ok"] is True
    assert status["session"]["session_epoch"] == session.session_epoch
    assert status["session"]["barge_in_supported"] is True
    assert status["policy"]["stale_result_suppression"] is True
    assert status["policy"]["interrupt_boundary"] == "between synthesis chunks"
