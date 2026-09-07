from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

from app.voice_session_v9 import VoiceSessionRuntime, VoiceSessionState


class VoiceRuntimeError(RuntimeError):
    """Raised when the governed v10 voice runtime cannot safely continue."""


@dataclass(frozen=True)
class VoiceRuntimePolicy:
    max_input_characters: int = 12_000
    max_chunk_characters: int = 220
    max_chunks_per_turn: int = 64
    target_first_audio_ms: int = 1_500

    def validate(self) -> None:
        if not 256 <= self.max_input_characters <= 100_000:
            raise VoiceRuntimeError("max_input_characters is outside the governed range")
        if not 64 <= self.max_chunk_characters <= 600:
            raise VoiceRuntimeError("max_chunk_characters is outside the governed range")
        if not 1 <= self.max_chunks_per_turn <= 256:
            raise VoiceRuntimeError("max_chunks_per_turn is outside the governed range")
        if not 50 <= self.target_first_audio_ms <= 30_000:
            raise VoiceRuntimeError("target_first_audio_ms is outside the governed range")


@dataclass(frozen=True)
class VoiceTurnResult:
    ok: bool
    turn_id: str | None
    interrupted: bool
    stale: bool
    chunks_requested: int
    chunks_completed: int
    first_audio_ms: int | None
    total_elapsed_ms: int
    target_first_audio_ms: int
    latency_target_met: bool | None
    audio: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "turn_id": self.turn_id,
            "interrupted": self.interrupted,
            "stale": self.stale,
            "chunks_requested": self.chunks_requested,
            "chunks_completed": self.chunks_completed,
            "first_audio_ms": self.first_audio_ms,
            "total_elapsed_ms": self.total_elapsed_ms,
            "target_first_audio_ms": self.target_first_audio_ms,
            "latency_target_met": self.latency_target_met,
            "audio": [dict(item) for item in self.audio],
            "error": self.error,
        }


@dataclass(frozen=True)
class VoiceTranscriptionResult:
    ok: bool
    interrupted: bool
    stale: bool
    elapsed_ms: int
    transcript: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "interrupted": self.interrupted,
            "stale": self.stale,
            "elapsed_ms": self.elapsed_ms,
            "transcript": dict(self.transcript) if self.transcript is not None else None,
            "error": self.error,
        }


class LowLatencyVoiceRuntime:
    """Interruptible audio transport over the existing v9 voice-session authority.

    `VoiceSessionRuntime` remains the single source of truth for hands-free lifecycle,
    active-turn identity, and barge-in state. `VoiceAdapter` remains the single source
    of truth for STT/TTS engines and workspace-scoped audio files. This v10 layer adds
    bounded chunked synthesis, safe-boundary interruption, stale-result suppression,
    and turn-level latency evidence without creating a competing session subsystem.
    """

    def __init__(
        self,
        adapter: Any,
        session_runtime: VoiceSessionRuntime,
        *,
        policy: VoiceRuntimePolicy | None = None,
    ) -> None:
        self.adapter = adapter
        self.session_runtime = session_runtime
        self.policy = policy or VoiceRuntimePolicy()
        self.policy.validate()

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "session": self.session_runtime.status(),
            "policy": {
                "max_input_characters": self.policy.max_input_characters,
                "max_chunk_characters": self.policy.max_chunk_characters,
                "max_chunks_per_turn": self.policy.max_chunks_per_turn,
                "target_first_audio_ms": self.policy.target_first_audio_ms,
                "interrupt_boundary": "between synthesis chunks",
                "stale_result_suppression": True,
            },
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text).strip())

    def _chunks(self, text: str) -> tuple[str, ...]:
        normalized = self._normalize_text(text)
        if not normalized:
            raise VoiceRuntimeError("voice response text is empty")
        if len(normalized) > self.policy.max_input_characters:
            raise VoiceRuntimeError("voice response exceeds the governed input bound")

        max_chars = self.policy.max_chunk_characters
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", normalized) if item.strip()]
        output: list[str] = []
        for sentence in sentences or [normalized]:
            remaining = sentence
            while len(remaining) > max_chars:
                boundary = max(
                    remaining.rfind(", ", 0, max_chars + 1),
                    remaining.rfind("; ", 0, max_chars + 1),
                    remaining.rfind(" ", 0, max_chars + 1),
                )
                if boundary < max_chars // 2:
                    boundary = max_chars
                chunk = remaining[:boundary].strip(" ,;")
                if chunk:
                    output.append(chunk)
                remaining = remaining[boundary:].strip(" ,;")
            if remaining:
                output.append(remaining)

        if not output:
            raise VoiceRuntimeError("voice response produced no synthesis chunks")
        if len(output) > self.policy.max_chunks_per_turn:
            raise VoiceRuntimeError("voice response exceeds the governed chunk bound")
        return tuple(output)

    def _active_turn_id(self) -> str | None:
        turn = self.session_runtime.active_turn
        return turn.turn_id if turn is not None else None

    def _turn_is_current_and_speaking(self, turn_id: str) -> bool:
        turn = self.session_runtime.active_turn
        return bool(
            turn is not None
            and turn.turn_id == turn_id
            and not turn.interrupted
            and self.session_runtime.state == VoiceSessionState.SPEAKING
        )

    def interrupt(self, reason: str = "barge_in") -> dict[str, Any]:
        return self.session_runtime.interrupt(reason)

    async def synthesize_active_turn(
        self,
        text: str,
        *,
        voice_id: str = "sentinel",
        speed: float | None = None,
        volume: float = 1.0,
        tone: str | None = None,
        fallback: bool = True,
        use_cuda: bool = False,
    ) -> VoiceTurnResult:
        chunks = self._chunks(text)
        if self.session_runtime.active_turn is None:
            raise VoiceRuntimeError("no active voice turn")
        if self.session_runtime.state == VoiceSessionState.THINKING:
            self.session_runtime.begin_speaking()
        if self.session_runtime.state != VoiceSessionState.SPEAKING:
            raise VoiceRuntimeError(f"cannot synthesize while voice session is {self.session_runtime.state.value}")

        turn_id = self._active_turn_id()
        if not turn_id:
            raise VoiceRuntimeError("active voice turn identity is unavailable")

        started = time.monotonic()
        first_audio_ms: int | None = None
        audio: list[dict[str, Any]] = []

        for index, chunk in enumerate(chunks):
            if not self._turn_is_current_and_speaking(turn_id):
                elapsed = int((time.monotonic() - started) * 1000)
                return VoiceTurnResult(
                    ok=False,
                    turn_id=turn_id,
                    interrupted=True,
                    stale=True,
                    chunks_requested=len(chunks),
                    chunks_completed=len(audio),
                    first_audio_ms=first_audio_ms,
                    total_elapsed_ms=elapsed,
                    target_first_audio_ms=self.policy.target_first_audio_ms,
                    latency_target_met=(first_audio_ms <= self.policy.target_first_audio_ms) if first_audio_ms is not None else None,
                    audio=tuple(audio),
                    error="voice turn was interrupted",
                )

            filename = f"v10-{turn_id[:12]}-{index:03d}.wav"
            result = await asyncio.to_thread(
                self.adapter.speak,
                chunk,
                filename,
                175,
                voice_id,
                speed,
                volume,
                use_cuda,
                fallback,
                tone,
            )

            if not self._turn_is_current_and_speaking(turn_id):
                elapsed = int((time.monotonic() - started) * 1000)
                return VoiceTurnResult(
                    ok=False,
                    turn_id=turn_id,
                    interrupted=True,
                    stale=True,
                    chunks_requested=len(chunks),
                    chunks_completed=len(audio),
                    first_audio_ms=first_audio_ms,
                    total_elapsed_ms=elapsed,
                    target_first_audio_ms=self.policy.target_first_audio_ms,
                    latency_target_met=(first_audio_ms <= self.policy.target_first_audio_ms) if first_audio_ms is not None else None,
                    audio=tuple(audio),
                    error="voice turn was interrupted during synthesis",
                )

            if not isinstance(result, dict) or not result.get("ok") or not result.get("path"):
                self.session_runtime.interrupt("synthesis_failed")
                elapsed = int((time.monotonic() - started) * 1000)
                return VoiceTurnResult(
                    ok=False,
                    turn_id=turn_id,
                    interrupted=False,
                    stale=False,
                    chunks_requested=len(chunks),
                    chunks_completed=len(audio),
                    first_audio_ms=first_audio_ms,
                    total_elapsed_ms=elapsed,
                    target_first_audio_ms=self.policy.target_first_audio_ms,
                    latency_target_met=(first_audio_ms <= self.policy.target_first_audio_ms) if first_audio_ms is not None else None,
                    audio=tuple(audio),
                    error=str((result or {}).get("error") or "voice synthesis failed"),
                )

            elapsed_now = int((time.monotonic() - started) * 1000)
            if first_audio_ms is None:
                first_audio_ms = elapsed_now
            audio.append(
                {
                    "index": index,
                    "text_characters": len(chunk),
                    "path": str(result["path"]),
                    "engine": result.get("engine"),
                    "adapter_elapsed_ms": result.get("elapsed_ms"),
                    "ready_at_ms": elapsed_now,
                }
            )

        total_elapsed = int((time.monotonic() - started) * 1000)
        self.session_runtime.complete_turn()
        return VoiceTurnResult(
            ok=True,
            turn_id=turn_id,
            interrupted=False,
            stale=False,
            chunks_requested=len(chunks),
            chunks_completed=len(audio),
            first_audio_ms=first_audio_ms,
            total_elapsed_ms=total_elapsed,
            target_first_audio_ms=self.policy.target_first_audio_ms,
            latency_target_met=(first_audio_ms <= self.policy.target_first_audio_ms) if first_audio_ms is not None else None,
            audio=tuple(audio),
        )

    async def transcribe_audio(
        self,
        path: str,
        *,
        model_size: str = "base",
        language: str | None = None,
        initial_prompt: str | None = None,
        device: str = "auto",
        compute_type: str = "int8",
    ) -> VoiceTranscriptionResult:
        epoch = self.session_runtime.session_epoch
        if self.session_runtime.state == VoiceSessionState.STOPPED:
            raise VoiceRuntimeError("voice session is stopped")
        started = time.monotonic()
        result = await asyncio.to_thread(
            self.adapter.transcribe,
            path,
            model_size,
            language,
            initial_prompt,
            device,
            compute_type,
        )
        elapsed = int((time.monotonic() - started) * 1000)

        stale = bool(
            self.session_runtime.session_epoch != epoch
            or self.session_runtime.state == VoiceSessionState.STOPPED
        )
        if stale:
            return VoiceTranscriptionResult(
                ok=False,
                interrupted=True,
                stale=True,
                elapsed_ms=elapsed,
                error="transcription result became stale after session transition",
            )
        if not isinstance(result, dict) or not result.get("ok"):
            return VoiceTranscriptionResult(
                ok=False,
                interrupted=False,
                stale=False,
                elapsed_ms=elapsed,
                error=str((result or {}).get("error") or "transcription failed"),
            )
        return VoiceTranscriptionResult(
            ok=True,
            interrupted=False,
            stale=False,
            elapsed_ms=elapsed,
            transcript=dict(result),
        )


__all__ = [
    "LowLatencyVoiceRuntime",
    "VoiceRuntimeError",
    "VoiceRuntimePolicy",
    "VoiceTranscriptionResult",
    "VoiceTurnResult",
]
