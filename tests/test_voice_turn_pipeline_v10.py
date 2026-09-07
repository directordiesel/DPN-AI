from __future__ import annotations

import asyncio

from app.low_latency_voice_runtime_v10 import LowLatencyVoiceRuntime
from app.voice_session_v9 import VoiceSessionRuntime, VoiceSessionState
from app.voice_turn_pipeline_v10 import VoiceTurnPipeline


class PipelineVoiceAdapter:
    def __init__(self) -> None:
        self.speak_calls: list[str] = []
        self.transcribe_calls: list[str] = []
        self.transcript_text: object = "turn on the lights"

    def transcribe(self, path, model_size, language, initial_prompt, device, compute_type):
        self.transcribe_calls.append(path)
        return {
            "ok": True,
            "path": path,
            "text": self.transcript_text,
            "segments": [{"start": 0.0, "end": 0.6, "text": str(self.transcript_text)}],
            "language": language or "en",
            "model": model_size,
            "elapsed_ms": 8,
        }

    def speak(self, text, filename, rate, voice_id, speed, volume, use_cuda, fallback, tone):
        self.speak_calls.append(text)
        return {
            "ok": True,
            "path": f"generated/voice/{filename}",
            "engine": "fake",
            "elapsed_ms": 9,
        }


def _pipeline(tmp_path, reasoner):
    session = VoiceSessionRuntime(tmp_path, hands_free=True)
    session.start(hands_free=True)
    adapter = PipelineVoiceAdapter()
    runtime = LowLatencyVoiceRuntime(adapter, session)
    return adapter, session, VoiceTurnPipeline(runtime, session, reasoner)


def test_voice_turn_pipeline_runs_stt_reasoning_session_and_tts(tmp_path):
    adapter, session, pipeline = _pipeline(tmp_path, lambda text: f"Confirmed: {text}.")

    result = asyncio.run(pipeline.run_audio_turn("uploads/voice/request.wav"))

    assert result.ok is True
    assert result.transcript == "turn on the lights"
    assert result.response_text == "Confirmed: turn on the lights."
    assert result.synthesis is not None
    assert result.synthesis["ok"] is True
    assert adapter.transcribe_calls == ["uploads/voice/request.wav"]
    assert adapter.speak_calls
    assert session.state == VoiceSessionState.LISTENING
    assert session.active_turn is None


def test_voice_turn_pipeline_supports_async_reasoner(tmp_path):
    async def reasoner(text: str) -> str:
        await asyncio.sleep(0)
        return f"Async response to {text}"

    _, _, pipeline = _pipeline(tmp_path, reasoner)
    result = asyncio.run(pipeline.run_audio_turn("uploads/voice/request.wav"))
    assert result.ok is True
    assert result.response_text == "Async response to turn on the lights"


def test_voice_turn_pipeline_fails_closed_on_empty_reasoning(tmp_path):
    adapter, session, pipeline = _pipeline(tmp_path, lambda _: "")

    result = asyncio.run(pipeline.run_audio_turn("uploads/voice/request.wav"))

    assert result.ok is False
    assert result.error == "reasoning failed: ValueError"
    assert adapter.speak_calls == []
    assert session.state == VoiceSessionState.LISTENING


def test_voice_turn_pipeline_bounds_reasoner_output_before_tts(tmp_path):
    adapter, _, pipeline = _pipeline(tmp_path, lambda _: "x" * 33)
    pipeline.max_response_characters = 32

    result = asyncio.run(pipeline.run_audio_turn("uploads/voice/request.wav"))

    assert result.ok is False
    assert result.error == "reasoning failed: ValueError"
    assert adapter.speak_calls == []


def test_voice_turn_pipeline_rejects_non_string_structured_transcript(tmp_path):
    adapter, session, pipeline = _pipeline(tmp_path, lambda text: f"should not run: {text}")
    adapter.transcript_text = {"unexpected": "mapping"}

    result = asyncio.run(pipeline.run_audio_turn("uploads/voice/request.wav"))

    assert result.ok is False
    assert result.transcript is None
    assert result.response_text is None
    assert result.synthesis is None
    assert result.error == "transcription payload does not contain string text"
    assert adapter.speak_calls == []
    assert session.state == VoiceSessionState.LISTENING
