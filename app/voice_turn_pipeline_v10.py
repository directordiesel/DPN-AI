from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.low_latency_voice_runtime_v10 import LowLatencyVoiceRuntime
from app.voice_session_v9 import VoiceSessionRuntime, VoiceSessionState


Reasoner = Callable[[str], str | Awaitable[str]]


@dataclass(frozen=True)
class VoiceTurnPipelineResult:
    ok: bool
    transcript: str | None
    response_text: str | None
    synthesis: dict[str, Any] | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "transcript": self.transcript,
            "response_text": self.response_text,
            "synthesis": self.synthesis,
            "error": self.error,
        }


class VoiceTurnPipeline:
    """Governed STT -> reasoning -> existing-session -> TTS coordinator.

    The pipeline owns no model/session state. It composes the existing v10 voice
    runtime with the existing VoiceSessionRuntime and an injected reasoner.
    """

    def __init__(
        self,
        runtime: LowLatencyVoiceRuntime,
        session: VoiceSessionRuntime,
        reasoner: Reasoner,
        *,
        max_response_characters: int = 12000,
    ) -> None:
        if max_response_characters < 1 or max_response_characters > 50000:
            raise ValueError("max_response_characters must be between 1 and 50000")
        self.runtime = runtime
        self.session = session
        self.reasoner = reasoner
        self.max_response_characters = max_response_characters

    @staticmethod
    def _transcript_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise ValueError("transcription payload must be a structured mapping")
        value = payload.get("text")
        if not isinstance(value, str):
            raise ValueError("transcription payload does not contain string text")
        text = value.strip()
        if not text:
            raise ValueError("transcription payload contains empty text")
        return text

    async def _reason(self, transcript: str) -> str:
        result = self.reasoner(transcript)
        if inspect.isawaitable(result):
            result = await result
        text = str(result or "").strip()
        if not text:
            raise ValueError("reasoner returned an empty response")
        if len(text) > self.max_response_characters:
            raise ValueError("reasoner response exceeds configured bound")
        return text

    async def run_audio_turn(self, path: str, **transcription_options: Any) -> VoiceTurnPipelineResult:
        transcription = await self.runtime.transcribe_audio(path, **transcription_options)
        if not transcription.ok or transcription.stale or transcription.interrupted or not transcription.transcript:
            return VoiceTurnPipelineResult(
                ok=False,
                transcript=None,
                response_text=None,
                synthesis=None,
                error=transcription.error or "transcription did not produce an active transcript",
            )

        try:
            transcript = self._transcript_text(transcription.transcript)
        except ValueError as exc:
            return VoiceTurnPipelineResult(
                ok=False,
                transcript=None,
                response_text=None,
                synthesis=None,
                error=str(exc),
            )

        try:
            response = await self._reason(transcript)
        except Exception as exc:
            return VoiceTurnPipelineResult(
                ok=False,
                transcript=transcript,
                response_text=None,
                synthesis=None,
                error=f"reasoning failed: {type(exc).__name__}",
            )

        if self.session.state == VoiceSessionState.STOPPED:
            return VoiceTurnPipelineResult(
                ok=False,
                transcript=transcript,
                response_text=response,
                synthesis=None,
                error="voice session is not running",
            )

        self.session.begin_turn(transcript)
        synthesis = await self.runtime.synthesize_active_turn(response)
        synthesis_payload = synthesis.to_dict() if hasattr(synthesis, "to_dict") else dict(synthesis)
        if not synthesis.ok or synthesis.stale or synthesis.interrupted:
            return VoiceTurnPipelineResult(
                ok=False,
                transcript=transcript,
                response_text=response,
                synthesis=synthesis_payload,
                error=synthesis.error or "synthesis did not complete",
            )

        return VoiceTurnPipelineResult(
            ok=True,
            transcript=transcript,
            response_text=response,
            synthesis=synthesis_payload,
            error=None,
        )


__all__ = ["Reasoner", "VoiceTurnPipeline", "VoiceTurnPipelineResult"]
