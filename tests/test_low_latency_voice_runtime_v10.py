from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from app.low_latency_voice_runtime_v10 import (
    LowLatencyVoiceRuntime,
    VoiceRuntimeError,
    VoiceRuntimePolicy,
)


class FakeVoiceAdapter:
    def __init__(self) -> None:
        self.speak_calls: list[tuple] = []
        self.transcribe_calls: list[tuple] = []
        self.block_speak = False
        self.block_transcribe = False
        self.speak_started = threading.Event()
        self.speak_release = threading.Event()
        self.transcribe_started = threading.Event()
        self.transcribe_release = threading.Event()

    def speak(self, text, filename, rate, voice_id, speed, volume, use_cuda, fallback, tone):
        self.speak_calls.append((text, filename, rate, voice_id, speed, volume, use_cuda, fallback, tone))
        if self.block_speak:
            self.speak_started.set()
            self.speak_release.wait(timeout=2)
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


def test_voice_runtime_chunks_response_and_reports_first_audio_latency():
    adapter = FakeVoiceAdapter()
    runtime = LowLatencyVoiceRuntime(
        adapter,
        policy=VoiceRuntimePolicy(max_chunk_characters=80, target_first_audio_ms=1500),
    )
    session = runtime.create_session()

    result = asyncio.run(
        runtime.synthesize_turn(
            session["session_id"],
            "First sentence is intentionally long enough to create bounded delivery. Second sentence follows immediately.",
        )
    )

    assert result.ok is True
    assert result.interrupted is False
    assert result.stale is False
    assert result.chunks_requested >= 2
    assert result.chunks_completed == result.chunks_requested
    assert len(adapter.speak_calls) == result.chunks_completed
    assert result.first_audio_ms is not None
    assert result.latency_target_met is True
    assert all(item["path"].startswith("generated/voice/v10-") for item in result.audio)


def test_voice_runtime_barge_in_invalidates_active_synthesis_at_safe_boundary():
    async def scenario():
        adapter = FakeVoiceAdapter()
        adapter.block_speak = True
        runtime = LowLatencyVoiceRuntime(adapter, policy=VoiceRuntimePolicy(max_chunk_characters=70))
        session_id = runtime.create_session()["session_id"]

        task = asyncio.create_task(
            runtime.synthesize_turn(
                session_id,
                "This first chunk is deliberately long enough to enter synthesis. This second chunk must never be synthesized after interruption.",
            )
        )
        assert await asyncio.to_thread(adapter.speak_started.wait, 1.0)
        interrupted = runtime.interrupt(session_id)
        adapter.speak_release.set()
        result = await task
        return adapter, runtime, session_id, interrupted, result

    adapter, runtime, session_id, interrupted, result = asyncio.run(scenario())
    assert interrupted["ok"] is True
    assert result.ok is False
    assert result.interrupted is True
    assert result.stale is True
    assert result.chunks_completed == 0
    assert len(adapter.speak_calls) == 1
    assert runtime.session_status(session_id)["interrupted_turns"] == 1


def test_voice_runtime_discards_transcription_that_becomes_stale():
    async def scenario():
        adapter = FakeVoiceAdapter()
        adapter.block_transcribe = True
        runtime = LowLatencyVoiceRuntime(adapter)
        session_id = runtime.create_session()["session_id"]
        task = asyncio.create_task(runtime.transcribe_turn(session_id, "uploads/voice/input.wav"))
        assert await asyncio.to_thread(adapter.transcribe_started.wait, 1.0)
        runtime.interrupt(session_id)
        adapter.transcribe_release.set()
        return await task

    result = asyncio.run(scenario())
    assert result.ok is False
    assert result.interrupted is True
    assert result.stale is True
    assert result.transcript is None


def test_new_voice_turn_invalidates_older_generation_and_next_turn_can_succeed():
    adapter = FakeVoiceAdapter()
    runtime = LowLatencyVoiceRuntime(adapter)
    session_id = runtime.create_session()["session_id"]

    first = asyncio.run(runtime.synthesize_turn(session_id, "Short response."))
    second = asyncio.run(runtime.synthesize_turn(session_id, "Another short response."))

    assert first.ok is True
    assert second.ok is True
    assert second.generation > first.generation
    assert runtime.session_status(session_id)["turn_count"] == 2


def test_voice_runtime_fails_closed_before_adapter_call_for_oversized_response():
    adapter = FakeVoiceAdapter()
    runtime = LowLatencyVoiceRuntime(adapter, policy=VoiceRuntimePolicy(max_input_characters=256))
    session_id = runtime.create_session()["session_id"]

    with pytest.raises(VoiceRuntimeError, match="input bound"):
        asyncio.run(runtime.synthesize_turn(session_id, "x" * 257))

    assert adapter.speak_calls == []


def test_closed_voice_session_rejects_future_work():
    adapter = FakeVoiceAdapter()
    runtime = LowLatencyVoiceRuntime(adapter)
    session_id = runtime.create_session()["session_id"]
    closed = runtime.close_session(session_id)

    assert closed["closed"] is True
    with pytest.raises(VoiceRuntimeError, match="closed"):
        asyncio.run(runtime.synthesize_turn(session_id, "Do not speak."))


def test_voice_policy_rejects_unsafe_chunk_configuration():
    with pytest.raises(VoiceRuntimeError, match="max_chunk_characters"):
        LowLatencyVoiceRuntime(FakeVoiceAdapter(), policy=VoiceRuntimePolicy(max_chunk_characters=10))
