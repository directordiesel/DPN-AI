import base64
import json

import pytest

from app.api_v2_contracts import (
    APIV2ContractError,
    APIV2Envelope,
    decode_cursor,
    encode_cursor,
    negotiate_capabilities,
    validate_envelope,
    verify_monotonic_sequence,
)


def test_valid_envelope_and_monotonic_sequence():
    events = [
        APIV2Envelope("2.0", 10, "task.updated", {"id": "a"}, {}),
        APIV2Envelope("2.0", 11, "task.updated", {"id": "b"}, {"source": "test"}),
    ]
    assert validate_envelope(events[0]) is events[0]
    assert verify_monotonic_sequence(events) is True
    assert verify_monotonic_sequence(events, start_sequence=10) is True


def test_sequence_gap_fails_closed():
    events = [
        APIV2Envelope("2.0", 1, "task.updated", {}, {}),
        APIV2Envelope("2.0", 3, "task.updated", {}, {}),
    ]
    assert verify_monotonic_sequence(events) is False


@pytest.mark.parametrize(
    "envelope",
    [
        APIV2Envelope("3.0", 0, "task.updated", {}, {}),
        APIV2Envelope("2.0", -1, "task.updated", {}, {}),
        APIV2Envelope("2.0", True, "task.updated", {}, {}),
        APIV2Envelope("2.0", 0, "Bad Event", {}, {}),
    ],
)
def test_invalid_envelope_fields_are_rejected(envelope):
    with pytest.raises(APIV2ContractError):
        validate_envelope(envelope)


def test_payload_size_is_bounded():
    envelope = APIV2Envelope("2.0", 1, "task.updated", {"blob": "x" * 5000}, {})
    with pytest.raises(APIV2ContractError, match="size limit"):
        validate_envelope(envelope, max_event_bytes=1024)


def test_nonfinite_json_values_are_rejected():
    envelope = APIV2Envelope("2.0", 1, "metrics.sample", {"value": float("nan")}, {})
    with pytest.raises(APIV2ContractError, match="non-JSON"):
        validate_envelope(envelope)


def test_cursor_round_trip_and_tamper_detection():
    token = encode_cursor(sequence=42, stream="tasks")
    assert decode_cursor(token) == {"version": "2.0", "sequence": 42, "stream": "tasks"}

    padding = "=" * (-len(token) % 4)
    decoded = base64.urlsafe_b64decode((token + padding).encode("ascii"))
    body, checksum = decoded.rsplit(b".", 1)
    data = json.loads(body.decode("utf-8"))
    data["sequence"] = 43
    tampered_body = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    tampered = base64.urlsafe_b64encode(tampered_body + b"." + checksum).decode("ascii").rstrip("=")
    with pytest.raises(APIV2ContractError, match="integrity"):
        decode_cursor(tampered)


def test_capability_negotiation_is_deduplicated_and_ordered():
    result = negotiate_capabilities(
        ["events.read", "tasks.read", "events.read", "tasks.write"],
        ["tasks.read", "events.read"],
    )
    assert result.requested == ("events.read", "tasks.read", "tasks.write")
    assert result.accepted == ("events.read", "tasks.read")
    assert result.rejected == ("tasks.write",)


def test_invalid_capability_identifier_is_rejected():
    with pytest.raises(APIV2ContractError, match="identifier"):
        negotiate_capabilities(["events/read"], ["events.read"])


def test_metadata_key_count_is_bounded():
    metadata = {f"k{i}": i for i in range(65)}
    with pytest.raises(APIV2ContractError, match="too many"):
        validate_envelope(APIV2Envelope("2.0", 1, "task.updated", {}, metadata))
