from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


API_V2_VERSION = "2.0"
MAX_EVENT_BYTES = 262_144
MAX_METADATA_KEYS = 64
MAX_METADATA_KEY_LENGTH = 96
MAX_CAPABILITIES = 64

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")


class APIV2ContractError(ValueError):
    """Raised when an API v2 transport contract fails closed."""


@dataclass(frozen=True)
class APIV2Envelope:
    version: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CapabilityNegotiation:
    requested: tuple[str, ...]
    supported: tuple[str, ...]
    accepted: tuple[str, ...]
    rejected: tuple[str, ...]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def validate_envelope(
    envelope: APIV2Envelope,
    *,
    max_event_bytes: int = MAX_EVENT_BYTES,
) -> APIV2Envelope:
    if not isinstance(envelope, APIV2Envelope):
        raise APIV2ContractError("event must be an APIV2Envelope")
    if envelope.version != API_V2_VERSION:
        raise APIV2ContractError("unsupported API v2 protocol version")
    if isinstance(envelope.sequence, bool) or not isinstance(envelope.sequence, int) or envelope.sequence < 0:
        raise APIV2ContractError("sequence must be a non-negative integer")
    if not _EVENT_TYPE_RE.fullmatch(str(envelope.event_type or "")):
        raise APIV2ContractError("event_type is invalid")
    if not isinstance(envelope.payload, dict):
        raise APIV2ContractError("payload must be an object")
    if not isinstance(envelope.metadata, dict):
        raise APIV2ContractError("metadata must be an object")
    if len(envelope.metadata) > MAX_METADATA_KEYS:
        raise APIV2ContractError("metadata contains too many keys")
    for key in envelope.metadata:
        key_text = str(key)
        if not key_text or len(key_text) > MAX_METADATA_KEY_LENGTH:
            raise APIV2ContractError("metadata key is invalid")
    if isinstance(max_event_bytes, bool) or not isinstance(max_event_bytes, int) or max_event_bytes < 1024:
        raise APIV2ContractError("max_event_bytes must be an integer of at least 1024")
    try:
        encoded = _canonical_json(
            {
                "version": envelope.version,
                "sequence": envelope.sequence,
                "event_type": envelope.event_type,
                "payload": envelope.payload,
                "metadata": envelope.metadata,
            }
        )
    except (TypeError, ValueError) as exc:
        raise APIV2ContractError("event contains non-JSON or non-finite values") from exc
    if len(encoded) > max_event_bytes:
        raise APIV2ContractError("event exceeds configured size limit")
    return envelope


def encode_cursor(*, sequence: int, stream: str) -> str:
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise APIV2ContractError("cursor sequence must be a non-negative integer")
    stream_text = str(stream or "")
    if not _EVENT_TYPE_RE.fullmatch(stream_text):
        raise APIV2ContractError("cursor stream is invalid")
    body = _canonical_json({"sequence": sequence, "stream": stream_text, "version": API_V2_VERSION})
    checksum = hashlib.sha256(body).hexdigest().encode("ascii")
    token = base64.urlsafe_b64encode(body + b"." + checksum).decode("ascii").rstrip("=")
    return token


def decode_cursor(token: str) -> dict[str, Any]:
    raw = str(token or "").strip()
    if not raw or len(raw) > 2048:
        raise APIV2ContractError("cursor is empty or oversized")
    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
        body, checksum = decoded.rsplit(b".", 1)
    except Exception as exc:  # noqa: BLE001
        raise APIV2ContractError("cursor encoding is invalid") from exc
    expected = hashlib.sha256(body).hexdigest().encode("ascii")
    if checksum != expected:
        raise APIV2ContractError("cursor integrity check failed")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIV2ContractError("cursor payload is invalid") from exc
    if not isinstance(data, dict) or data.get("version") != API_V2_VERSION:
        raise APIV2ContractError("cursor version is unsupported")
    sequence = data.get("sequence")
    stream = data.get("stream")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise APIV2ContractError("cursor sequence is invalid")
    if not isinstance(stream, str) or not _EVENT_TYPE_RE.fullmatch(stream):
        raise APIV2ContractError("cursor stream is invalid")
    return {"version": API_V2_VERSION, "sequence": sequence, "stream": stream}


def negotiate_capabilities(
    requested: Iterable[str],
    supported: Iterable[str],
) -> CapabilityNegotiation:
    requested_values = tuple(dict.fromkeys(str(item).strip().lower() for item in requested if str(item).strip()))
    supported_values = tuple(dict.fromkeys(str(item).strip().lower() for item in supported if str(item).strip()))
    if len(requested_values) > MAX_CAPABILITIES or len(supported_values) > MAX_CAPABILITIES:
        raise APIV2ContractError("capability list exceeds configured limit")
    for capability in (*requested_values, *supported_values):
        if not _CAPABILITY_RE.fullmatch(capability):
            raise APIV2ContractError("capability identifier is invalid")
    supported_set = set(supported_values)
    accepted = tuple(item for item in requested_values if item in supported_set)
    rejected = tuple(item for item in requested_values if item not in supported_set)
    return CapabilityNegotiation(
        requested=requested_values,
        supported=supported_values,
        accepted=accepted,
        rejected=rejected,
    )


def verify_monotonic_sequence(envelopes: Iterable[APIV2Envelope], *, start_sequence: int | None = None) -> bool:
    expected = start_sequence
    try:
        for envelope in envelopes:
            validate_envelope(envelope)
            if expected is None:
                expected = envelope.sequence
            if envelope.sequence != expected:
                return False
            expected += 1
    except APIV2ContractError:
        return False
    return True


__all__ = [
    "API_V2_VERSION",
    "APIV2ContractError",
    "APIV2Envelope",
    "CapabilityNegotiation",
    "decode_cursor",
    "encode_cursor",
    "negotiate_capabilities",
    "validate_envelope",
    "verify_monotonic_sequence",
]
