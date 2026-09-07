from __future__ import annotations

from typing import Any

from app.low_latency_voice_runtime_v10 import LowLatencyVoiceRuntime


def register(registry: Any) -> None:
    voice = getattr(registry, "voice", None)
    session_runtime = getattr(registry, "voice_session_runtime", None)
    register_tool = getattr(registry, "register", None)
    if voice is None or session_runtime is None or not callable(register_tool):
        return

    runtime = LowLatencyVoiceRuntime(voice, session_runtime)
    registry.low_latency_voice_runtime_v10 = runtime

    register_tool(
        name="voice_v10_status",
        description=(
            "Report the v10 low-latency voice transport policy together with the existing hands-free voice session state."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=runtime.status,
        gate="voice",
        risk="read",
    )
    register_tool(
        name="voice_v10_synthesize_active_turn",
        description=(
            "Synthesize the response for the existing active voice turn in bounded chunks. "
            "Barge-in uses the existing voice session interruption state and stops at the next safe chunk boundary."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 12000},
                "voice_id": {"type": "string", "enum": ["sentinel", "aurora", "system"], "default": "sentinel"},
                "speed": {"type": ["number", "null"], "minimum": 0.57, "maximum": 1.42, "default": None},
                "volume": {"type": "number", "minimum": 0.1, "maximum": 1.0, "default": 1.0},
                "tone": {"type": ["string", "null"], "maxLength": 40, "default": None},
                "fallback": {"type": "boolean", "default": True},
                "use_cuda": {"type": "boolean", "default": False},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        function=runtime.synthesize_active_turn,
        gate="voice",
        risk="execute",
    )
    register_tool(
        name="voice_v10_transcribe_audio",
        description=(
            "Transcribe workspace-scoped audio through the existing VoiceAdapter in a worker thread and discard results that become stale after a session stop/restart."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "model_size": {"type": "string", "maxLength": 40, "default": "base"},
                "language": {"type": ["string", "null"], "maxLength": 20, "default": None},
                "initial_prompt": {"type": ["string", "null"], "maxLength": 1000, "default": None},
                "device": {"type": "string", "enum": ["auto", "cpu", "cuda"], "default": "auto"},
                "compute_type": {"type": "string", "maxLength": 40, "default": "int8"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        function=runtime.transcribe_audio,
        gate="voice",
        risk="execute",
    )
    register_tool(
        name="voice_v10_interrupt",
        description=(
            "Interrupt the currently speaking v10 voice turn through the existing session authority. "
            "The active engine call is never killed unsafely; stale audio is suppressed at the next chunk boundary."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "maxLength": 200, "default": "barge_in"},
            },
            "additionalProperties": False,
        },
        function=runtime.interrupt,
        gate="voice",
        risk="execute",
    )


__all__ = ["register"]
