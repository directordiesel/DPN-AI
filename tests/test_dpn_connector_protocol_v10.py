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


def test_matching_read_evidence_is_accepted():
    registry = DPNConnectorRegistry()
    registry.register(_manifest(), _Adapter())
    evidence = asyncio.run(registry.execute(ConnectorRequest("github-primary", ConnectorAction.READ, "repository")))
    assert evidence.connector_id == "github-primary"
    assert evidence.action == ConnectorAction.READ
    assert evidence.health == ConnectorHealth.HEALTHY
    assert evidence.provenance["request_id"] == "evidence-1"
