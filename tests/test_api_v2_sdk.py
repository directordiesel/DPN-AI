import pytest

from app.api_v2_contracts import APIV2ContractError, APIV2Envelope, decode_cursor, encode_cursor
from app.api_v2_sdk import APIV2ClientSession, MAX_REPLAY_EVENTS
from app.api_v2_surface import build_readiness


def _event(sequence: int, event_type: str = "chat.delta") -> APIV2Envelope:
    return APIV2Envelope(
        version="2.0",
        sequence=sequence,
        event_type=event_type,
        payload={"text": f"token-{sequence}"},
        metadata={},
    )


def test_session_negotiates_capabilities_and_fails_explicitly_on_mismatch():
    readiness = build_readiness(supported=("protocol.envelopes", "protocol.cursor"))
    session = APIV2ClientSession(
        readiness=readiness,
        stream="chat.events",
        requested_capabilities=("protocol.envelopes", "transport.websocket"),
    )
    assert session.compatible is False
    assert session.accepted_capabilities == ("protocol.envelopes",)
    assert session.rejected_capabilities == ("transport.websocket",)
    with pytest.raises(APIV2ContractError, match="does not support"):
        session.require_compatible()


def test_session_records_monotonic_events_and_builds_resume_cursor():
    session = APIV2ClientSession(readiness=build_readiness(), stream="chat.events")
    session.record_event(_event(7))
    session.record_event(_event(8))
    with pytest.raises(APIV2ContractError, match="expected 9"):
        session.record_event(_event(10))

    token = session.latest_cursor()
    assert token is not None
    assert decode_cursor(token) == {"version": "2.0", "sequence": 8, "stream": "chat.events"}


def test_resume_cursor_sets_next_sequence_before_buffering():
    session = APIV2ClientSession(readiness=build_readiness(), stream="jobs.events")
    token = encode_cursor(sequence=40, stream="jobs.events")
    assert session.resume_from_cursor(token) == 41
    session.record_event(_event(41, "job.progress"))
    with pytest.raises(APIV2ContractError, match="before events are buffered"):
        session.resume_from_cursor(token)


def test_resume_cursor_cannot_cross_streams():
    session = APIV2ClientSession(readiness=build_readiness(), stream="jobs.events")
    token = encode_cursor(sequence=3, stream="chat.events")
    with pytest.raises(APIV2ContractError, match="different stream"):
        session.resume_from_cursor(token)


def test_replay_window_is_bounded_and_detects_lost_history():
    session = APIV2ClientSession(readiness=build_readiness(), stream="chat.events", max_replay_events=2)
    session.record_event(_event(1))
    session.record_event(_event(2))
    session.record_event(_event(3))

    assert [event.sequence for event in session.replay_from(2)] == [2, 3]
    assert session.replay_from(4) == ()
    with pytest.raises(APIV2ContractError, match="older than"):
        session.replay_from(1)
    with pytest.raises(APIV2ContractError, match="ahead"):
        session.replay_from(5)


def test_status_contains_no_event_payloads_and_does_not_invent_live_transport():
    readiness = build_readiness(transport="websocket", live=False)
    session = APIV2ClientSession(readiness=readiness, stream="chat.events")
    session.record_event(_event(0))
    status = session.status()
    assert status.transport == "websocket"
    assert status.transport_live is False
    assert status.buffered_events == 1
    assert status.next_sequence == 1
    assert not hasattr(status, "payload")


@pytest.mark.parametrize("value", [0, MAX_REPLAY_EVENTS + 1, True, 1.5])
def test_replay_capacity_is_strictly_bounded(value):
    with pytest.raises(APIV2ContractError, match="max_replay_events"):
        APIV2ClientSession(readiness=build_readiness(), stream="chat.events", max_replay_events=value)


def test_invalid_stream_identifier_fails_closed():
    with pytest.raises(APIV2ContractError):
        APIV2ClientSession(readiness=build_readiness(), stream="https://example.com/stream")
