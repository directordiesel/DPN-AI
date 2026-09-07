from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable


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


@dataclass
class _VoiceSessionState:
    session_id: str
    generation: int = 0
    closed: bool = False
    created_monotonic: float = field(default_factory=time.monotonic)
    turn_count: int = 0
    interrupted_turns: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


@dataclass(frozen=True)
class VoiceTurnResult:
    ok: bool
    session_id: str
    generation: int
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
            "session_id": self.session_id,
            "generation": self.generation,
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
    session_id: str
    generation: int
    interrupted: bool
    stale: bool
    elapsed_ms: int
    transcript: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "session_id": self.session_id,
            "generation": self.generation,
            "interrupted": self.interrupted,
            "stale": self.stale,
            "elapsed_ms": self.elapsed_ms,
            "transcript": dict(self.transcript) if self.transcript is not None else None,
            "error": self.error,
        }


class LowLatencyVoiceRuntime:
    """Interruptible turn orchestration over the existing VoiceAdapter.

    The mature adapter remains responsible for STT/TTS engines, filesystem containment,
    model selection, and generated audio. This runtime adds short synthesis chunks,
    generation-based barge-in cancellation, stale-result suppression, bounded work, and
    turn-level latency evidence. It deliberately never kills worker threads mid-engine
    call; interruption takes effect at the next safe chunk boundary.
    """

    def __init__(self, adapter: Any, *, policy: VoiceRuntimePolicy | None = None) -> None:
        self.adapter = adapter
        self.policy = policy or VoiceRuntimePolicy()
        self.policy.validate()
        self._sessions: dict[str, _VoiceSessionState] = {}
        self._sessions_lock = threading.RLock()

    def create_session(self) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        state = _VoiceSessionState(session_id=session_id)
        with self._sessions_lock:
            self._sessions[session_id] = state
        return {
            "ok": True,
            "session_id": session_id,
            "generation": 0,
            "policy": {
                "max_input_characters": self.policy.max_input_characters,
                "max_chunk_characters": self.policy.max_chunk_characters,
                "max_chunks_per_turn": self.policy.max_chunks_per_turn,
                "target_first_audio_ms": self.policy.target_first_audio_ms,
                "interrupt_boundary": "between synthesis chunks",
            },
        }

    def _session(self, session_id: str) -> _VoiceSessionState:
        key = str(session_id).strip()
        with self._sessions_lock:
            state = self._sessions.get(key)
        if state is None:
            raise VoiceRuntimeError("unknown voice session")
        with state.lock:
            if state.closed:
                raise VoiceRuntimeError("voice session is closed")
        return state

    def interrupt(self, session_id: str) -> dict[str, Any]:
        state = self._session(session_id)
        with state.lock:
            state.generation += 1
            state.interrupted_turns += 1
            generation = state.generation
        return {
            "ok": True,
            "session_id": state.session_id,
            "generation": generation,
            "effect": "active work becomes stale and stops at the next safe boundary",
        }

    def close_session(self, session_id: str) -> dict[str, Any]:
        state = self._session(session_id)
        with state.lock:
            state.generation += 1
            state.closed = True
            generation = state.generation
        return {"ok": True, "session_id": state.session_id, "generation": generation, "closed": True}

    def session_status(self, session_id: str) -> dict[str, Any]:
        state = self._session(session_id)
        with state.lock:
            return {
                "ok": True,
                "session_id": state.session_id,
                "generation": state.generation,
                "closed": state.closed,
                "turn_count": state.turn_count,
                "interrupted_turns": state.interrupted_turns,
                "age_ms": int((time.monotonic() - state.created_monotonic) * 1000),
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

    @staticmethod
    def _is_current(state: _VoiceSessionState, generation: int) -> bool:
        with state.lock:
            return not state.closed and state.generation == generation

    def _begin_turn(self, state: _VoiceSessionState) -> int:
        with state.lock:
            if state.closed:
                raise VoiceRuntimeError("voice session is closed")
            state.generation += 1
            state.turn_count += 1
            return state.generation

    async def synthesize_turn(
        self,
        session_id: str,
        text: str,
        *,
        voice_id: str = "sentinel",
        speed: float | None = None,
        volume: float = 1.0,
        tone: str | None = None,
        fallback: bool = True,
        use_cuda: bool = False,
    ) -> VoiceTurnResult:
        state = self._session(session_id)
        chunks = self._chunks(text)
        generation = self._begin_turn(state)
        started = time.monotonic()
        first_audio_ms: int | None = None
        audio: list[dict[str, Any]] = []

        for index, chunk in enumerate(chunks):
            if not self._is_current(state, generation):
                elapsed = int((time.monotonic() - started) * 1000)
                return VoiceTurnResult(
                    ok=False,
                    session_id=state.session_id,
                    generation=generation,
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

            filename = f"v10-{state.session_id[:12]}-{generation:06d}-{index:03d}.wav"
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

            if not self._is_current(state, generation):
                elapsed = int((time.monotonic() - started) * 1000)
                return VoiceTurnResult(
                    ok=False,
                    session_id=state.session_id,
                    generation=generation,
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
                elapsed = int((time.monotonic() - started) * 1000)
                return VoiceTurnResult(
                    ok=False,
                    session_id=state.session_id,
                    generation=generation,
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
        return VoiceTurnResult(
            ok=True,
            session_id=state.session_id,
            generation=generation,
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

    async def transcribe_turn(
        self,
        session_id: str,
        path: str,
        *,
        model_size: str = "base",
        language: str | None = None,
        initial_prompt: str | None = None,
        device: str = "auto",
        compute_type: str = "int8",
    ) -> VoiceTranscriptionResult:
        state = self._session(session_id)
        generation = self._begin_turn(state)
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

        if not self._is_current(state, generation):
            return VoiceTranscriptionResult(
                ok=False,
                session_id=state.session_id,
                generation=generation,
                interrupted=True,
                stale=True,
                elapsed_ms=elapsed,
                error="transcription result became stale after interruption",
            )
        if not isinstance(result, dict) or not result.get("ok"):
            return VoiceTranscriptionResult(
                ok=False,
                session_id=state.session_id,
                generation=generation,
                interrupted=False,
                stale=False,
                elapsed_ms=elapsed,
                error=str((result or {}).get("error") or "transcription failed"),
            )
        return VoiceTranscriptionResult(
            ok=True,
            session_id=state.session_id,
            generation=generation,
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
