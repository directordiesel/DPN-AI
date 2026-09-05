import hashlib
import hmac

import pytest

from app.sdk_integrations_v9 import (
    CapabilityDescriptor,
    IntegrationOperation,
    SDKContractError,
    SDKIntegrationRuntime,
    SDKRequest,
)


def _caps():
    return [
        CapabilityDescriptor(
            name="projects",
            version="v2",
            operations=frozenset({IntegrationOperation.READ, IntegrationOperation.WRITE}),
            requires_approval=True,
        ),
        CapabilityDescriptor(
            name="health",
            version="v2",
            operations=frozenset({IntegrationOperation.READ}),
        ),
    ]


def test_discovery_is_stable_and_unique():
    items = SDKIntegrationRuntime.discover(reversed(_caps()))
    assert [item.name for item in items] == ["health", "projects"]


def test_unknown_capability_fails_closed():
    with pytest.raises(SDKContractError, match="not discovered"):
        SDKIntegrationRuntime.validate_request(
            SDKRequest(capability="missing", operation=IntegrationOperation.READ), _caps()
        )


def test_write_requires_idempotency_and_approval():
    with pytest.raises(SDKContractError, match="idempotency"):
        SDKIntegrationRuntime.validate_request(
            SDKRequest(capability="projects", operation=IntegrationOperation.WRITE, approval_granted=True), _caps()
        )
    with pytest.raises(SDKContractError, match="approval"):
        SDKIntegrationRuntime.validate_request(
            SDKRequest(capability="projects", operation=IntegrationOperation.WRITE, idempotency_key="req-1"), _caps()
        )
    result = SDKIntegrationRuntime.validate_request(
        SDKRequest(
            capability="projects",
            operation=IntegrationOperation.WRITE,
            idempotency_key="req-1",
            approval_granted=True,
        ),
        _caps(),
    )
    assert result.name == "projects"


def test_signed_event_verification_detects_tampering():
    key = b"event-test-key"
    event = SDKIntegrationRuntime.build_event(
        event_type="mission.updated", sequence=7, payload={"mission_id": "m1", "status": "running"}, signing_key=key
    )
    assert SDKIntegrationRuntime.verify_event(event, signing_key=key) is True
    tampered = type(event)(event.event_id, event.event_type, event.sequence, {"mission_id": "m1", "status": "done"}, event.signature)
    assert SDKIntegrationRuntime.verify_event(tampered, signing_key=key) is False


def test_webhook_hmac_verification():
    body = b'{"event":"task.completed"}'
    key = b"webhook-key"
    signature = hmac.new(key, body, hashlib.sha256).hexdigest()
    assert SDKIntegrationRuntime.verify_webhook(raw_body=body, signature=f"sha256={signature}", signing_key=key) is True
    assert SDKIntegrationRuntime.verify_webhook(raw_body=body + b"x", signature=signature, signing_key=key) is False
