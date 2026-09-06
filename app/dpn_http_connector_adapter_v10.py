from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.connectors import ConnectorHub
from app.db import Database
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


_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_CREATE_METHODS = {"POST"}
_UPDATE_METHODS = {"PUT", "PATCH"}
_DELETE_METHODS = {"DELETE"}


class HTTPConnectorProtocolAdapter:
    """DPN Connector Protocol adapter over the existing hardened ConnectorHub.

    The adapter deliberately reuses ConnectorHub for URL validation, SSRF blocking,
    encrypted-secret resolution, redirect refusal, response bounds, and method
    allow-listing. It does not create a second HTTP execution path.
    """

    def __init__(self, db: Database, hub: ConnectorHub, connector_id: str) -> None:
        self.db = db
        self.hub = hub
        self.connector_id = connector_id

    async def health(self) -> ConnectorHealth:
        connector = self.db.get_connector(self.connector_id)
        if not connector:
            return ConnectorHealth.UNCONFIGURED
        if not connector.get("enabled"):
            return ConnectorHealth.UNAVAILABLE
        if connector.get("kind") != "http":
            return ConnectorHealth.UNAVAILABLE
        config = connector.get("config") or {}
        valid, _reason = self.hub._validate_base_url(str(config.get("base_url") or ""))
        return ConnectorHealth.HEALTHY if valid else ConnectorHealth.UNAVAILABLE

    @staticmethod
    def _method_for(request: ConnectorRequest) -> str:
        raw = str(request.payload.get("method") or "").strip().upper()
        if raw:
            return raw
        if request.action in {ConnectorAction.READ, ConnectorAction.SEARCH}:
            return "GET"
        if request.action == ConnectorAction.CREATE:
            return "POST"
        if request.action == ConnectorAction.UPDATE:
            return "PATCH"
        if request.action == ConnectorAction.DELETE:
            return "DELETE"
        raise ConnectorProtocolError(f"HTTP connector action {request.action.value} has no request method")

    @staticmethod
    def _validate_action_method(action: ConnectorAction, method: str) -> None:
        valid = (
            (action in {ConnectorAction.READ, ConnectorAction.SEARCH} and method in _READ_METHODS)
            or (action == ConnectorAction.CREATE and method in _CREATE_METHODS)
            or (action == ConnectorAction.UPDATE and method in _UPDATE_METHODS)
            or (action == ConnectorAction.DELETE and method in _DELETE_METHODS)
        )
        if not valid:
            raise ConnectorProtocolError(
                f"HTTP method {method} is not compatible with connector action {action.value}"
            )

    async def execute(self, request: ConnectorRequest) -> ConnectorEvidence:
        method = self._method_for(request)
        self._validate_action_method(request.action, method)
        path = str(request.payload.get("path") or "")
        params = request.payload.get("params")
        json_body = request.payload.get("json_body")
        timeout_seconds = int(request.payload.get("timeout_seconds") or 30)

        result = await self.hub.request(
            self.connector_id,
            method=method,
            path=path,
            params=params if isinstance(params, dict) else None,
            json_body=json_body,
            timeout_seconds=timeout_seconds,
        )
        ok = bool(result.get("ok"))
        health = ConnectorHealth.HEALTHY if ok else ConnectorHealth.DEGRADED
        provenance = {
            "transport": "http",
            "method": method,
            "url": result.get("url"),
            "status_code": result.get("status_code"),
            "content_type": result.get("content_type"),
        }
        # Never place request payloads, headers, secret templates, or response bodies
        # into the audit log. The protocol audit contains only bounded metadata.
        self.db.audit(
            "connector.protocol_execution",
            f"DPN connector {request.action.value} via HTTP",
            {
                "connector_id": self.connector_id,
                "action": request.action.value,
                "resource": request.resource,
                "method": method,
                "ok": ok,
                "status_code": result.get("status_code"),
            },
        )
        return ConnectorEvidence(
            connector_id=self.connector_id,
            action=request.action,
            resource=request.resource,
            provider_kind="http",
            ok=ok,
            health=health,
            result=result.get("response") if ok else None,
            error="" if ok else str(result.get("error") or f"HTTP status {result.get('status_code', 'unknown')}"),
            provenance=provenance,
        )


def http_manifest(connector: dict[str, Any]) -> ConnectorManifest:
    """Translate a persisted ConnectorHub record into a fail-closed v10 manifest."""
    config = connector.get("config") or {}
    methods = {str(item).strip().upper() for item in config.get("allowed_methods", ["GET"]) if str(item).strip()}
    capabilities: list[ConnectorCapability] = [
        ConnectorCapability(ConnectorAction.DISCOVER, risk=ConnectorRisk.READ_ONLY),
        ConnectorCapability(ConnectorAction.CAPABILITIES, risk=ConnectorRisk.READ_ONLY),
        ConnectorCapability(ConnectorAction.HEALTH, risk=ConnectorRisk.READ_ONLY),
    ]
    if methods & _READ_METHODS:
        capabilities.extend(
            [
                ConnectorCapability(ConnectorAction.READ, risk=ConnectorRisk.READ_ONLY),
                ConnectorCapability(ConnectorAction.SEARCH, risk=ConnectorRisk.READ_ONLY),
            ]
        )
    if methods & _CREATE_METHODS:
        capabilities.append(
            ConnectorCapability(
                ConnectorAction.CREATE,
                risk=ConnectorRisk.WRITE,
                approval_required=True,
            )
        )
    if methods & _UPDATE_METHODS:
        capabilities.append(
            ConnectorCapability(
                ConnectorAction.UPDATE,
                risk=ConnectorRisk.WRITE,
                approval_required=True,
            )
        )
    if methods & _DELETE_METHODS:
        capabilities.append(
            ConnectorCapability(
                ConnectorAction.DELETE,
                risk=ConnectorRisk.DESTRUCTIVE,
                approval_required=True,
            )
        )
    return ConnectorManifest(
        connector_id=str(connector.get("id") or ""),
        kind="http",
        display_name=str(connector.get("name") or "HTTP Connector"),
        capabilities=tuple(capabilities),
        configured=bool(config.get("base_url")),
        enabled=bool(connector.get("enabled")),
        local=False,
        version="1",
        metadata={"transport": "http"},
    )


class HTTPConnectorProtocolService:
    """Synchronizes persisted HTTP connectors into the v10 protocol registry."""

    def __init__(self, db: Database, hub: ConnectorHub) -> None:
        self.db = db
        self.hub = hub

    def registry(self) -> DPNConnectorRegistry:
        registry = DPNConnectorRegistry()
        for connector in self.db.list_connectors():
            if connector.get("kind") != "http":
                continue
            manifest = http_manifest(connector)
            registry.register(manifest, HTTPConnectorProtocolAdapter(self.db, self.hub, manifest.connector_id))
        return registry

    def catalog(self) -> dict[str, Any]:
        manifests = self.registry().discover()
        return {
            "ok": True,
            "protocol": "dpn-connector-v1",
            "connectors": [
                {
                    "connector_id": item.connector_id,
                    "kind": item.kind,
                    "display_name": item.display_name,
                    "configured": item.configured,
                    "enabled": item.enabled,
                    "version": item.version,
                    "capabilities": [
                        {
                            "action": cap.action.value,
                            "resource": cap.resource,
                            "risk": cap.risk.value,
                            "approval_required": cap.approval_required,
                        }
                        for cap in item.capabilities
                    ],
                }
                for item in manifests
            ],
        }

    async def read(
        self,
        connector_id: str,
        path: str = "",
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 30,
        *,
        search: bool = False,
    ) -> dict[str, Any]:
        """Expose only read/search execution at this service boundary.

        Write/destructive protocol actions exist in manifests but are intentionally not
        exposed here. They require a trusted approval-token integration rather than a
        caller-supplied boolean.
        """
        action = ConnectorAction.SEARCH if search else ConnectorAction.READ
        request = ConnectorRequest(
            connector_id=connector_id,
            action=action,
            payload={
                "method": "GET",
                "path": path,
                "params": params or {},
                "timeout_seconds": timeout_seconds,
            },
        )
        evidence = await self.registry().execute(request)
        return {
            "ok": evidence.ok,
            "connector_id": evidence.connector_id,
            "action": evidence.action.value,
            "resource": evidence.resource,
            "health": evidence.health.value,
            "result": evidence.result,
            "error": evidence.error,
            "provenance": evidence.provenance,
        }


__all__ = [
    "HTTPConnectorProtocolAdapter",
    "HTTPConnectorProtocolService",
    "http_manifest",
]
