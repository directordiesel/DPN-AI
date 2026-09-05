from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class VoiceSessionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    STOPPED = "stopped"


@dataclass(frozen=True)
class MultimodalAttachment:
    path: str
    media_type: str


@dataclass
class VoiceTurn:
    turn_id: str
    user_text: str
    source: str = "voice"
    attachments: list[MultimodalAttachment] = field(default_factory=list)
    state: VoiceSessionState = VoiceSessionState.THINKING
    interrupted: bool = False
    interruption_reason: str | None = None


class VoiceSessionRuntime:
    """Deterministic hands-free voice and multimodal session state manager."""

    ALLOWED_MEDIA_TYPES = {"image", "audio", "document"}
    ALLOWED_SUFFIXES = {
        "image": {".png", ".jpg", ".jpeg", ".webp"},
        "audio": {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".wma"},
        "document": {".txt", ".md", ".pdf", ".docx", ".xlsx", ".csv", ".json"},
    }
    MAX_ATTACHMENTS = 8
    MAX_INTERRUPTION_REASON = 200
    ALLOWED_TURN_SOURCES = {"voice", "microphone", "text", "remote"}

    def __init__(self, workspace: Path, hands_free: bool = False) -> None:
        self.workspace = workspace.resolve()
        self.hands_free = bool(hands_free)
        self.state = VoiceSessionState.IDLE
        self.turn_index = 0
        self.active_turn: VoiceTurn | None = None
        self.session_epoch = 0
        self.interruption_count = 0

    def _resolve_attachment(self, attachment: MultimodalAttachment) -> dict[str, str]:
        media_type = str(attachment.media_type).strip().lower()
        if media_type not in self.ALLOWED_MEDIA_TYPES:
            raise ValueError(f"Unsupported media_type: {media_type}")
        raw = str(attachment.path).strip()
        if not raw:
            raise ValueError("Attachment path is required")
        target = (self.workspace / raw).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Attachment path escapes the workspace") from exc
        if not target.exists() or not target.is_file():
            raise ValueError("Attachment does not exist")
        if target.suffix.lower() not in self.ALLOWED_SUFFIXES[media_type]:
            raise ValueError(f"Unsupported {media_type} attachment format: {target.suffix.lower() or 'unknown'}")
        return {"path": target.relative_to(self.workspace).as_posix(), "media_type": media_type}

    def start(self, hands_free: bool | None = None) -> dict[str, Any]:
        if self.active_turn is not None:
            raise ValueError("Cannot restart a voice session while a turn is active")
        if hands_free is not None:
            self.hands_free = bool(hands_free)
        self.session_epoch += 1
        self.state = VoiceSessionState.LISTENING
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self.active_turn is not None:
            self.active_turn.interrupted = True
            self.active_turn.interruption_reason = "session_stopped"
            self.active_turn.state = VoiceSessionState.STOPPED
        self.state = VoiceSessionState.STOPPED
        self.active_turn = None
        return self.status()

    def begin_turn(
        self,
        user_text: str,
        attachments: list[MultimodalAttachment] | None = None,
        source: str = "voice",
    ) -> dict[str, Any]:
        if self.active_turn is not None:
            raise ValueError("A voice turn is already active")
        if self.state == VoiceSessionState.STOPPED:
            raise ValueError("Voice session is stopped; start it before beginning a turn")
        text = str(user_text or "").strip()
        if not text:
            raise ValueError("Voice turn text is required")
        normalized_source = str(source or "voice").strip().lower() or "voice"
        if normalized_source not in self.ALLOWED_TURN_SOURCES:
            raise ValueError(f"Unsupported voice turn source: {normalized_source}")
        items = list(attachments or [])
        if len(items) > self.MAX_ATTACHMENTS:
            raise ValueError(f"A voice turn supports at most {self.MAX_ATTACHMENTS} attachments")
        normalized = [self._resolve_attachment(item) for item in items]
        self.turn_index += 1
        material = f"{self.session_epoch}|{self.turn_index}|{text}|{normalized_source}|{normalized}"
        turn_id = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
        self.active_turn = VoiceTurn(
            turn_id=turn_id,
            user_text=text,
            source=normalized_source,
            attachments=[MultimodalAttachment(**item) for item in normalized],
        )
        self.state = VoiceSessionState.THINKING
        return self.turn_payload()

    def begin_speaking(self) -> dict[str, Any]:
        if not self.active_turn:
            raise ValueError("No active voice turn")
        if self.state != VoiceSessionState.THINKING:
            raise ValueError(f"Cannot begin speaking while voice session is {self.state.value}")
        self.state = VoiceSessionState.SPEAKING
        self.active_turn.state = VoiceSessionState.SPEAKING
        return self.turn_payload()

    def interrupt(self, reason: str = "barge_in") -> dict[str, Any]:
        if not self.active_turn or self.state != VoiceSessionState.SPEAKING:
            return {"ok": False, "interrupted": False, "state": self.state.value}
        normalized_reason = str(reason or "barge_in").strip() or "barge_in"
        if len(normalized_reason) > self.MAX_INTERRUPTION_REASON:
            raise ValueError(f"Interruption reason exceeds {self.MAX_INTERRUPTION_REASON} characters")
        self.state = VoiceSessionState.INTERRUPTED
        self.active_turn.state = VoiceSessionState.INTERRUPTED
        self.active_turn.interrupted = True
        self.active_turn.interruption_reason = normalized_reason
        self.interruption_count += 1
        return {"ok": True, "interrupted": True, **self.turn_payload()}

    def abandon_interrupted_turn(self) -> dict[str, Any]:
        if not self.active_turn or self.state != VoiceSessionState.INTERRUPTED:
            raise ValueError("No interrupted voice turn to abandon")
        payload = self.turn_payload()
        self.active_turn = None
        self.state = VoiceSessionState.LISTENING if self.hands_free else VoiceSessionState.IDLE
        return {**payload, "abandoned": True, "next_state": self.state.value}

    def complete_turn(self) -> dict[str, Any]:
        if not self.active_turn:
            raise ValueError("No active voice turn")
        if self.state == VoiceSessionState.INTERRUPTED:
            raise ValueError("Interrupted voice turn must be abandoned before continuing")
        if self.state not in {VoiceSessionState.THINKING, VoiceSessionState.SPEAKING}:
            raise ValueError(f"Cannot complete voice turn while session is {self.state.value}")
        payload = self.turn_payload()
        self.active_turn = None
        self.state = VoiceSessionState.LISTENING if self.hands_free else VoiceSessionState.IDLE
        return {**payload, "next_state": self.state.value}

    def turn_payload(self) -> dict[str, Any]:
        if not self.active_turn:
            return {"ok": False, "state": self.state.value, "turn": None}
        turn = self.active_turn
        return {
            "ok": True,
            "state": self.state.value,
            "turn": {
                "turn_id": turn.turn_id,
                "user_text": turn.user_text,
                "source": turn.source,
                "attachments": [
                    {"path": item.path, "media_type": item.media_type} for item in turn.attachments
                ],
                "modalities": sorted({"text", *(item.media_type for item in turn.attachments)}),
                "interrupted": turn.interrupted,
                "interruption_reason": turn.interruption_reason,
            },
        }

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "state": self.state.value,
            "hands_free": self.hands_free,
            "session_epoch": self.session_epoch,
            "turn_index": self.turn_index,
            "active_turn_id": self.active_turn.turn_id if self.active_turn else None,
            "barge_in_supported": True,
            "interruption_count": self.interruption_count,
            "live_microphone_capture": False,
            "live_microphone_reason": "No trusted platform microphone capture provider is configured in this runtime.",
            "max_attachments_per_turn": self.MAX_ATTACHMENTS,
        }
