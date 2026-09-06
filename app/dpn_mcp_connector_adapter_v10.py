from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.dpn_connector_protocol_v10 import (
    ConnectorAction,
    ConnectorCapability,
    ConnectorEvidence,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorProtocolError,
    ConnectorRequest,
    ConnectorRisk,
)
from app.mcp_bridge import MCPBridge


@dataclass(frozen=True)
class MCPConnectorBinding:
    server_id: str
    connector_id: str


class MCPConnectorProtocolAdapter:
    """Fail-closed DPN Connector Protocol adapter over one configured MCP server.

    MCP tools are treated as write-risk because their external side effects cannot be
    inferred safely from tool names or schemas. Every allow-listed tool call therefore
    requires the trusted approval path used by DPN Connector Protocol writes.
    """

    KIND = "mcp"

    def __init__(self, bridge: MCPBridge, server_id: str) -> None:
        self.bridge = bridge
        self.server_id = str(server_id).strip()
        if not self.server_id:
            raise ConnectorProtocolError("MCP server id is required")

    @property
    def connector_id(self) -> str:
        return f"mcp:{self.server_id}"

    def _server(self) -> dict[str, Any] | None:
        server = self.bridge.db.get_mcp_server(self.server_id)
        return dict(server) if isinstance(server, dict) else None

    def manifest(self) -> ConnectorManifest:
        server = self._server()
        if not server:
            return ConnectorManifest(
                connector_id=self.connector_id,
                kind=self.KIND,
                display_name=f"MCP {self.server_id}",
                capabilities=(),
                configured=False,
                enabled=False,
                local=False,
                metadata={"transport": "unknown", "approved_tool_count": 0},
            )

        allowed = sorted({str(item).strip() for item in (server.get("allowed_tools") or []) if str(item).strip()})
        capabilities: list[ConnectorCapability] = [
            ConnectorCapability(ConnectorAction.DISCOVER, resource="tools"),
            ConnectorCapability(ConnectorAction.HEALTH, resource="server"),
        ]
        capabilities.extend(
            ConnectorCapability(
                ConnectorAction.UPDATE,
                resource=f"tool:{name}",
                risk=ConnectorRisk.WRITE,
                approval_required=True,
            )
            for name in allowed
        )
        transport = str(server.get("transport") or "unknown").lower()
        return ConnectorManifest(
            connector_id=self.connector_id,
            kind=self.KIND,
            display_name=str(server.get("name") or self.server_id),
            capabilities=tuple(capabilities),
            configured=True,
            enabled=bool(server.get("enabled")),
            local=transport == "stdio",
            metadata={
                "transport": transport,
                "approved_tool_count": len(allowed),
            },
        )

    async def health(self) -> ConnectorHealth:
        server = self._server()
        if not server:
            return ConnectorHealth.UNCONFIGURED
        if not server.get("enabled"):
            return ConnectorHealth.UNAVAILABLE
        status = self.bridge.status()
        return ConnectorHealth.HEALTHY if status.get("available") else ConnectorHealth.DEGRADED

    @staticmethod
    def _bounded_error(value: Any) -> str:
        return str(value or "MCP operation failed")[:1000]

    async def execute(self, request: ConnectorRequest) -> ConnectorEvidence:
        if request.connector_id != self.connector_id:
            raise ConnectorProtocolError("MCP connector identity mismatch")
        server = self._server()
        if not server or not server.get("enabled"):
            raise ConnectorProtocolError("MCP server is not configured and enabled")

        health = await self.health()
        if request.action == ConnectorAction.HEALTH and request.resource == "server":
            return ConnectorEvidence(
                connector_id=self.connector_id,
                action=request.action,
                resource=request.resource,
                provider_kind=self.KIND,
                ok=True,
                health=health,
                result={"health": health.value},
                provenance={"provider": "mcp", "server_id": self.server_id, "operation": "health"},
            )

        if request.action == ConnectorAction.DISCOVER and request.resource == "tools":
            result = await self.bridge.discover(self.server_id)
            ok = bool(result.get("ok"))
            return ConnectorEvidence(
                connector_id=self.connector_id,
                action=request.action,
                resource=request.resource,
                provider_kind=self.KIND,
                ok=ok,
                health=health if ok else ConnectorHealth.DEGRADED,
                result=result if ok else None,
                error="" if ok else self._bounded_error(result.get("error")),
                provenance={"provider": "mcp", "server_id": self.server_id, "operation": "discover"},
            )

        if request.action != ConnectorAction.UPDATE or not request.resource.startswith("tool:"):
            raise ConnectorProtocolError("MCP connector action/resource is not executable")
        tool_name = request.resource[5:].strip()
        if not tool_name:
            raise ConnectorProtocolError("MCP tool resource is invalid")
        allowed = {str(item) for item in (server.get("allowed_tools") or [])}
        if tool_name not in allowed:
            raise ConnectorProtocolError("MCP tool is not in the current server allowlist")
        arguments = request.payload.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ConnectorProtocolError("MCP tool arguments must be an object")
        result = await self.bridge.call_tool(self.server_id, tool_name, arguments)
        ok = bool(result.get("ok"))
        return ConnectorEvidence(
            connector_id=self.connector_id,
            action=request.action,
            resource=request.resource,
            provider_kind=self.KIND,
            ok=ok,
            health=health if ok else ConnectorHealth.DEGRADED,
            result=result if ok else None,
            error="" if ok else self._bounded_error(result.get("error")),
            provenance={
                "provider": "mcp",
                "server_id": self.server_id,
                "operation": "call_tool",
                "tool": tool_name,
            },
        )


class MCPConnectorProtocolService:
    """Discovers MCP server configurations as protocol manifests without starting them."""

    def __init__(self, bridge: MCPBridge) -> None:
        self.bridge = bridge

    def adapters(self) -> list[MCPConnectorProtocolAdapter]:
        listing = self.bridge.list_servers()
        servers = listing.get("servers") if isinstance(listing, dict) else None
        if not isinstance(servers, list):
            return []
        adapters = []
        for server in servers:
            if isinstance(server, dict) and str(server.get("id") or "").strip():
                adapters.append(MCPConnectorProtocolAdapter(self.bridge, str(server["id"])))
        return sorted(adapters, key=lambda item: item.connector_id)

    def manifests(self) -> list[ConnectorManifest]:
        return [adapter.manifest() for adapter in self.adapters()]


__all__ = ["MCPConnectorBinding", "MCPConnectorProtocolAdapter", "MCPConnectorProtocolService"]
