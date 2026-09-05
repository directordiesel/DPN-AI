from __future__ import annotations

from typing import Any

from app.voice_session_v9 import MultimodalAttachment, VoiceSessionRuntime


def install_voice_session_tools(registry: Any) -> VoiceSessionRuntime | None:
    register = getattr(registry, "register", None)
    settings = getattr(registry, "settings", None)
    if not callable(register) or settings is None:
        return None

    runtime = VoiceSessionRuntime(settings.workspace_dir)
    registry.voice_session_runtime = runtime

    register(
        "voice_session_status",
        "Report v9 hands-free voice session state, interruption capability, and provider availability.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        runtime.status,
        risk="read",
    )
    register(
        "start_voice_session",
        "Start or resume a DPN AI voice session, optionally in hands-free mode.",
        {
            "type": "object",
            "properties": {"hands_free": {"type": ["boolean", "null"], "default": None}},
            "additionalProperties": False,
        },
        runtime.start,
        gate="voice",
        risk="execute",
    )
    register(
        "stop_voice_session",
        "Stop the active DPN AI voice session.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        runtime.stop,
        gate="voice",
        risk="execute",
    )

    def begin_voice_turn(
        user_text: str,
        attachments: list[dict[str, str]] | None = None,
        source: str = "voice",
    ) -> dict[str, Any]:
        items = [MultimodalAttachment(path=item["path"], media_type=item["media_type"]) for item in (attachments or [])]
        return runtime.begin_turn(user_text=user_text, attachments=items, source=source)

    register(
        "begin_voice_turn",
        "Begin a v9 voice/multimodal turn with bounded workspace attachments.",
        {
            "type": "object",
            "properties": {
                "user_text": {"type": "string", "minLength": 1},
                "attachments": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "media_type": {"type": "string", "enum": ["image", "audio", "document"]},
                        },
                        "required": ["path", "media_type"],
                        "additionalProperties": False,
                    },
                    "default": [],
                },
                "source": {
                    "type": "string",
                    "enum": ["voice", "microphone", "text", "remote"],
                    "default": "voice",
                },
            },
            "required": ["user_text"],
            "additionalProperties": False,
        },
        begin_voice_turn,
        gate="voice",
        risk="execute",
    )
    register(
        "voice_begin_speaking",
        "Mark the active voice turn as speaking before TTS playback begins.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        runtime.begin_speaking,
        gate="voice",
        risk="execute",
    )
    register(
        "interrupt_voice",
        "Interrupt active speech for barge-in behavior without deleting the turn record.",
        {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "maxLength": 200, "default": "barge_in"},
            },
            "additionalProperties": False,
        },
        runtime.interrupt,
        gate="voice",
        risk="execute",
    )
    register(
        "abandon_interrupted_voice_turn",
        "Abandon an interrupted turn and return the session to its safe next state.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        runtime.abandon_interrupted_turn,
        gate="voice",
        risk="execute",
    )
    register(
        "complete_voice_turn",
        "Complete the current non-interrupted voice turn and return to listening in hands-free mode or idle otherwise.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        runtime.complete_turn,
        gate="voice",
        risk="execute",
    )
    return runtime
