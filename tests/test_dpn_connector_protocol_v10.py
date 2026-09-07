from __future__ import annotations

import asyncio

import pytest

from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorCapability,
    ConnectorEvidence,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorProtocolError,
    ConnectorRequest,
    ConnectorRisk,
    DPNConnectorRegistry,
)


class _Adapter:
    def __init__(self, health=ConnectorHealth.HEALTHY, *, provider_kind="github", ok=True, provenance=True):
        self.health_value = health
        self.provider_kind = provider_kind
        self.ok = ok
        self.with_provenance = provenance
        self.calls = []

    async def health(self):
        return self.health_value

    async def execute(self, request):
        self.calls.append(request)
        return ConnectorEvidence(
            connector_id=request.connector_id,
            action=request.action,
            resource=request.resource,
            provider_kind=self.provider_kind,
            ok=self.ok,
            health=self.health_value,
            result={"items": []},
            provenance={"request_id": "evidence-1"} if self.with_provenance else {},
        )


def _manifest(*, configured=True, enabled=True):
    return ConnectorManifest(
        connector_id="github-primary",
        kind="github",
        display_name="GitHub Primary",
        configured=configured,
        enabled=enabled,
        capabilities=(
            ConnectorCapability(ConnectorAction.DISCOVER),
            ConnectorCapability(ConnectorAction.HEALTH),
            ConnectorCapability(ConnectorAction.READ, "repository"),
            ConnectorCapability(ConnectorAction.SEARCH, "repository"),
            ConnectorCapability(ConnectorAction.CREATE, "issue", ConnectorRisk.WRITE, approval_required=True),
            ConnectorCapability(ConnectorAction.DELETE, "issue", ConnectorRisk.DESTRUCTIVE, approval_required=True),
        ),
    )


def test_destructive_capability_must_require_approval():
    with pytest.raises(ConnectorProtocolError):
        ConnectorManifest(
            connector_id="bad",
            kind="test",
            display_name="Bad",
            capabilities=(ConnectorCapability(ConnectorAction.DELETE, risk=ConnectorRisk.DESTRUCTIVE),),
        ).validate()


def test_write_capability_cannot_claim_read_only_risk():
    with pytest.raises(ConnectorProtocolError):
        ConnectorManifest(
            connector_id="bad",
            kind="test",
            display_name="Bad",
            capabilities=(ConnectorCapability(ConnectorAction.CREATE, "item"),),
        ).validate()


@pytest.mark.parametrize(
    ("action", "risk"),
    [
        (ConnectorAction.READ, ConnectorRisk.WRITE),
        (ConnectorAction.CREATE, ConnectorRisk.READ_ONLY),
        (ConnectorAction.DELETE, ConnectorRisk.WRITE),
        (ConnectorAction.SUBSCRIBE, ConnectorRisk.WRITE),
        (ConnectorAction.AUTHENTICATE, ConnectorRisk.READ_ONLY),
    ],
)
def test_capability_risk_underclassification_or_mismatch_is_rejected(action, risk):
    with pytest.raises(ConnectorProtocolError, match="risk drift"):
        ConnectorCapability(action, "item", risk, approval_required=True).validate()


def test_conservative_write_overclassification_is_allowed():
    ConnectorCapability(
        ConnectorAction.CREATE,
        "item",
        ConnectorRisk.DESTRUCTIVE,
        approval_required=True,
    ).validate()


def test_state_changing_capabilities_must_require_approval():
    for action, risk in (
        (ConnectorAction.CREATE, ConnectorRisk.WRITE),
        (ConnectorAction.UPDATE, ConnectorRisk.WRITE),
        (ConnectorAction.DELETE, ConnectorRisk.DESTRUCTIVE),
        (ConnectorAction.REVOKE, ConnectorRisk.DESTRUCTIVE),
        (ConnectorAction.SUBSCRIBE, ConnectorRisk.SUBSCRIPTION),
    ):
        with pytest.raises(ConnectorProtocolError, match="must require approval"):
            ConnectorCapability(action, "item", risk, approval_required=False).validate()


def test_connector_boolean_state_and_approval_fields_are_strict():
    with pytest.raises(ConnectorProtocolError, match="state flags"):
        ConnectorManifest(
            "bad",
            "test",
            "Bad",
            (ConnectorCapability(ConnectorAction.READ),),
            configured="true",  # type: ignore[arg-type]
        ).validate()

    with pytest.raises(ConnectorProtocolError, match="approval requirement"):
        ConnectorCapability(
            ConnectorAction.CREATE,
            "item",
            ConnectorRisk.WRITE,
            approval_required=1,  # type: ignore[arg-type]
        ).validate()

    with pytest.raises(ConnectorProtocolError, match="connector approval must be boolean"):
        ConnectorRequest(
            "github-primary",
            ConnectorAction.CREATE,
            "issue",
            approval_granted="true",  # type: ignore[arg-type]
        ).validate()


def test_registry_discovery_is_deterministic():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter())
    names = [item.connector_id for item in registry.discover()]
    assert names == ["github-primary"]
    with pytest.raises(ConnectorProtocolError):
        registry.register(_manifest(), _Adapter())


def test_unconfigured_connector_fails_closed():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(configured=False), _Adapter())
    request = ConnectorRequest("github-primary", ConnectorAction.READ, "repository")
    with pytest.raises(ConnectorProtocolError, match="not configured"):
        asyncio.run(registry.execute(request))
    assert asyncio.run(registry.health("github-primary")) == ConnectorHealth.UNCONFIGURED


def test_undeclared_action_is_rejected():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter())
    request = ConnectorRequest("github-primary", ConnectorAction.SUBSCRIBE, "repository")
    with pytest.raises(ConnectorProtocolError, match="not declared"):
        asyncio.run(registry.execute(request))


def test_write_action_requires_explicit_approval():
    registry = DPNConnectorRegistry()
    adapter = _Adapter()
    registry.register(_manifest(), adapter)
    denied = ConnectorRequest("github-primary", ConnectorAction.CREATE, "issue")
    with pytest.raises(ConnectorProtocolError, match="requires explicit approval"):
        asyncio.run(registry.execute(denied))
    allowed = ConnectorRequest("github-primary", ConnectorAction.CREATE, "issue", approval_granted=True)
    evidence = asyncio.run(registry.execute(allowed))
    assert evidence.ok is True
    assert len(adapter.calls) == 1


def test_resource_scope_is_least_privilege():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter())
    request = ConnectorRequest("github-primary", ConnectorAction.READ, "organization")
    with pytest.raises(ConnectorProtocolError, match="not declared"):
        asyncio.run(registry.execute(request))


def test_unhealthy_connector_cannot_execute():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter(ConnectorHealth.UNAVAILABLE))
    request = ConnectorRequest("github-primary", ConnectorAction.READ, "repository")
    with pytest.raises(ConnectorProtocolError, match="not executable"):
        asyncio.run(registry.execute(request))


def test_success_requires_provider_identity_and_provenance():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter(provider_kind="wrong"))
    request = ConnectorRequest("github-primary", ConnectorAction.READ, "repository")
    with pytest.raises(ConnectorProtocolError, match="provider kind"):
        asyncio.run(registry.execute(request))

    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter(provenance=False))
    with pytest.raises(ConnectorProtocolError, match="requires provenance"):
        asyncio.run(registry.execute(request))


def test_connector_evidence_success_and_health_types_are_strict():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter(ok="yes"))  # type: ignore[arg-type]
    with pytest.raises(ConnectorProtocolError, match="success flag"):
        asyncio.run(registry.execute(ConnectorRequest("github-primary", ConnectorAction.READ, "repository")))

    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter(health="healthy"))  # type: ignore[arg-type]
    with pytest.raises(ConnectorProtocolError, match="not executable"):
        asyncio.run(registry.execute(ConnectorRequest("github-primary", ConnectorAction.READ, "repository")))


def test_matching_read_evidence_is_accepted():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter())
    evidence = asyncio.run(registry.execute(ConnectorRequest("github-primary", ConnectorAction.READ, "repository")))
    assert evidence.connector_id == "github-primary"
    assert evidence.action == ConnectorAction.READ
    assert evidence.health == ConnectorHealth.HEALTHY
    assert evidence.provenance["request_id"] == "evidence-1"
