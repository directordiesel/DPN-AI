import pytest

from app.api_v2_contracts import APIV2ContractError
from app.api_v2_surface import (
    APIV2Readiness,
    DEFAULT_API_V2_CAPABILITIES,
    build_readiness,
    negotiate_client,
    readiness_payload,
)


def test_default_readiness_is_explicitly_not_live():
    readiness = build_readiness()
    assert readiness.protocol_version == "2.0"
    assert readiness.transport == "contract-only"
    assert readiness.live is False
    assert readiness.authenticated_mount_required is True
    assert readiness.capabilities == DEFAULT_API_V2_CAPABILITIES
    assert "no API v2 transport" in readiness.limitations[0]


def test_websocket_readiness_does_not_claim_unmounted_transport():
    readiness = build_readiness(transport="websocket", live=False)
    assert readiness.live is False
    assert readiness.limitations == ("websocket transport is not mounted",)


def test_readonly_rest_can_be_declared_live_without_claiming_websocket():
    readiness = build_readiness(transport="rest-readonly", live=True)
    payload = readiness_payload(readiness)
    assert payload["transport"] == "rest-readonly"
    assert payload["live"] is True
    assert payload["limitations"] == ()


def test_capabilities_are_normalized_and_deduplicated():
    readiness = build_readiness(supported=["Protocol.Cursor", "protocol.cursor", "protocol.sequence"])
    assert readiness.capabilities == ("protocol.cursor", "protocol.sequence")


def test_client_negotiation_is_deterministic_and_fail_explicit():
    result = negotiate_client(["protocol.cursor", "future.write"])
    assert result["accepted"] == ("protocol.cursor",)
    assert result["rejected"] == ("future.write",)
    assert result["compatible"] is False
    assert result["supported"] == DEFAULT_API_V2_CAPABILITIES


def test_client_negotiation_accepts_supported_subset():
    result = negotiate_client(["protocol.envelopes", "protocol.sequence"])
    assert result["compatible"] is True
    assert result["rejected"] == ()


@pytest.mark.parametrize("transport", ["", "tcp", "sse", "admin-shell"])
def test_unknown_transport_declarations_fail_closed(transport):
    with pytest.raises(APIV2ContractError, match="transport"):
        build_readiness(transport=transport)


def test_readiness_payload_rejects_wrong_object_type():
    with pytest.raises(APIV2ContractError, match="APIV2Readiness"):
        readiness_payload({"live": True})


def test_readiness_is_immutable_contract_data():
    readiness = APIV2Readiness(
        protocol_version="2.0",
        transport="contract-only",
        live=False,
        authenticated_mount_required=True,
        capabilities=DEFAULT_API_V2_CAPABILITIES,
        limitations=("not mounted",),
    )
    with pytest.raises(AttributeError):
        readiness.live = True
