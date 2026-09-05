from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from app.api_v2_contracts import (
    API_V2_VERSION,
    APIV2ContractError,
    APIV2Envelope,
    decode_cursor,
    encode_cursor,
    negotiate_capabilities,
    validate_envelope,
)
from app.api_v2_surface import APIV2Readiness, DEFAULT_API_V2_CAPABILITIES


MAX_REPLAY_EVENTS = 4096


@dataclass(frozen=True)
class APIV2SessionStatus:
    protocol_version: str
    stream: str
    transport: str
    transport_live: bool
    accepted_capabilities: tuple[str, ...]
    rejected_capabilities: tuple[str, ...]
    buffered_events: int
    replay_capacity: int
    next_sequence: int | None


class APIV2ClientSession:
    """Transport-neutral API v2 SDK session state.

    The session validates negotiated capabilities, monotonic event sequencing,
    bounded replay memory, and resume cursors. It performs no network I/O and
    therefore never represents a configured transport as connected or live.
    """

    def __init__(
        self,
        *,
        readiness: APIV2Readiness,
        stream: str,
        requested_capabilities: Iterable[str] = (),
        max_replay_events: int = 256,
    ) -> None:
        if not isinstance(readiness, APIV2Readiness):
            raise APIV2ContractError("readiness must be APIV2Readiness")
        if readiness.protocol_version != API_V2_VERSION:
            raise APIV2ContractError("SDK session protocol version is incompatible")
        stream_text = str(stream or "").strip().lower()
        # Reuse cursor validation so stream identifiers follow the protocol's
        # canonical identifier constraints without duplicating a weaker parser.
        decode_cursor(encode_cursor(sequence=0, stream=stream_text))
        if isinstance(max_replay_events, bool) or not isinstance(max_replay_events, int):
            raise APIV2ContractError("max_replay_events must be an integer")
        if max_replay_events < 1 or max_replay_events > MAX_REPLAY_EVENTS:
            raise APIV2ContractError(f"max_replay_events must be between 1 and {MAX_REPLAY_EVENTS}")

        supported = readiness.capabilities or DEFAULT_API_V2_CAPABILITIES
        negotiation = negotiate_capabilities(requested_capabilities, supported)
        self.readiness = readiness
        self.stream = stream_text
        self.accepted_capabilities = negotiation.accepted
        self.rejected_capabilities = negotiation.rejected
        self.max_replay_events = max_replay_events
        self._events: deque[APIV2Envelope] = deque(maxlen=max_replay_events)
        self._next_sequence: int | None = None

    @property
    def compatible(self) -> bool:
        return not self.rejected_capabilities

    def require_compatible(self) -> None:
        if self.rejected_capabilities:
            joined = ", ".join(self.rejected_capabilities)
            raise APIV2ContractError(f"server does not support requested capabilities: {joined}")

    def resume_from_cursor(self, token: str) -> int:
        if self._events:
            raise APIV2ContractError("resume cursor must be applied before events are buffered")
        decoded = decode_cursor(token)
        if decoded["stream"] != self.stream:
            raise APIV2ContractError("resume cursor belongs to a different stream")
        self._next_sequence = int(decoded["sequence"]) + 1
        return self._next_sequence

    def record_event(self, envelope: APIV2Envelope) -> APIV2Envelope:
        value = validate_envelope(envelope)
        if self._next_sequence is not None and value.sequence != self._next_sequence:
            raise APIV2ContractError(
                f"event sequence mismatch: expected {self._next_sequence}, received {value.sequence}"
            )
        self._events.append(value)
        self._next_sequence = value.sequence + 1
        return value

    def latest_cursor(self) -> str | None:
        if self._next_sequence is None:
            return None
        return encode_cursor(sequence=self._next_sequence - 1, stream=self.stream)

    def replay_from(self, sequence: int) -> tuple[APIV2Envelope, ...]:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise APIV2ContractError("replay sequence must be a non-negative integer")
        if not self._events:
            return ()
        oldest = self._events[0].sequence
        newest = self._events[-1].sequence
        if sequence < oldest:
            raise APIV2ContractError("requested replay sequence is older than the retained replay window")
        if sequence > newest + 1:
            raise APIV2ContractError("requested replay sequence is ahead of the observed stream")
        return tuple(event for event in self._events if event.sequence >= sequence)

    def status(self) -> APIV2SessionStatus:
        return APIV2SessionStatus(
            protocol_version=API_V2_VERSION,
            stream=self.stream,
            transport=self.readiness.transport,
            transport_live=bool(self.readiness.live),
            accepted_capabilities=self.accepted_capabilities,
            rejected_capabilities=self.rejected_capabilities,
            buffered_events=len(self._events),
            replay_capacity=self.max_replay_events,
            next_sequence=self._next_sequence,
        )


__all__ = [
    "APIV2ClientSession",
    "APIV2SessionStatus",
    "MAX_REPLAY_EVENTS",
]
