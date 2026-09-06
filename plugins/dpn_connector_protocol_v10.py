from __future__ import annotations

from app.dpn_connector_ecosystem_v10 import DPNConnectorEcosystemService
from app.dpn_first_party_connectors_v10 import FirstPartyConnectorService
from app.dpn_http_connector_adapter_v10 import HTTPConnectorProtocolService
from app.dpn_mcp_connector_adapter_v10 import MCPConnectorProtocolService


def register(registry) -> None:
    service = HTTPConnectorProtocolService(registry.db, registry.connectors)
    mcp_service = MCPConnectorProtocolService(registry.mcp)
    ecosystem = DPNConnectorEcosystemService(service, mcp_service)
    first_party = FirstPartyConnectorService(registry.connectors)

    registry.register(
        name="dpn_connector_ecosystem_catalog",
        description="List the unified DPN Connector Protocol ecosystem across concrete transports without exposing connector secrets.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=ecosystem.catalog,
        gate="connectors",
        risk="read",
    )
    registry.register(
        name="dpn_connector_ecosystem_health",
        description="Return fail-closed health/readiness for all configured DPN Connector Protocol transports without executing external mutations.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=ecosystem.health,
        gate="connectors",
        risk="read",
    )
    registry.register(
        name="dpn_connector_profile_catalog",
        description="List curated first-party DPN connector profiles and required vault secret names without exposing secret values.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=first_party.catalog,
        gate="connectors",
        risk="read",
    )
    registry.register(
        name="dpn_connector_profile_install",
        description="Install a curated first-party connector profile using vault secret references only. Installation changes connector configuration and always requires explicit human approval.",
        parameters={
            "type": "object",
            "properties": {
                "profile_id": {"type": "string", "enum": ["discord", "github", "google", "microsoft_graph", "reddit", "slack"]},
                "name": {"type": "string", "default": ""},
                "enabled": {"type": "boolean", "default": False},
            },
            "required": ["profile_id"],
            "additionalProperties": False,
        },
        function=first_party.install,
        gate="connectors",
        risk="destructive",
    )
    registry.register(
        name="dpn_connector_catalog",
        description="List DPN Connector Protocol capabilities without exposing connector secrets.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=service.catalog,
        gate="connectors",
        risk="read",
    )
    registry.register(
        name="dpn_connector_read",
        description="Execute a least-privilege DPN Connector Protocol read/search through the hardened connector transport with bounded idempotent retries.",
        parameters={
            "type": "object",
            "properties": {
                "connector_id": {"type": "string"},
                "path": {"type": "string", "default": ""},
                "params": {"type": ["object", "null"], "default": None},
                "timeout_seconds": {"type": "integer", "default": 30},
                "retry_attempts": {"type": "integer", "default": 2, "minimum": 1, "maximum": 3},
                "search": {"type": "boolean", "default": False},
            },
            "required": ["connector_id"],
            "additionalProperties": False,
        },
        function=service.read,
        gate="connectors",
        risk="external",
    )
    registry.register(
        name="dpn_connector_write",
        description="Execute an explicitly human-approved DPN Connector Protocol create, update, or delete operation. This tool is always single-use approval gated and never automatically retried.",
        parameters={
            "type": "object",
            "properties": {
                "connector_id": {"type": "string"},
                "action": {"type": "string", "enum": ["create", "update", "delete"]},
                "path": {"type": "string", "default": ""},
                "method": {"type": "string", "default": ""},
                "params": {"type": ["object", "null"], "default": None},
                "json_body": {},
                "timeout_seconds": {"type": "integer", "default": 30},
            },
            "required": ["connector_id", "action"],
            "additionalProperties": False,
        },
        function=service.approved_write,
        gate="connectors",
        risk="destructive",
    )
    registry.register(
        name="dpn_connector_mcp_catalog",
        description="List configured MCP servers and only their explicitly allow-listed DPN Connector Protocol capabilities without starting a server process.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=mcp_service.catalog,
        gate="mcp",
        risk="read",
    )
    registry.register(
        name="dpn_connector_mcp_discover",
        description="Discover tools from one enabled MCP server through the existing hardened MCP bridge.",
        parameters={
            "type": "object",
            "properties": {"connector_id": {"type": "string"}},
            "required": ["connector_id"],
            "additionalProperties": False,
        },
        function=mcp_service.discover,
        gate="mcp",
        risk="external",
    )
    registry.register(
        name="dpn_connector_mcp_call",
        description="Execute one explicitly allow-listed MCP tool after single-use human approval. MCP tool side effects are treated as write-risk regardless of tool name.",
        parameters={
            "type": "object",
            "properties": {
                "connector_id": {"type": "string"},
                "tool_name": {"type": "string"},
                "arguments": {"type": ["object", "null"], "default": None},
            },
            "required": ["connector_id", "tool_name"],
            "additionalProperties": False,
        },
        function=mcp_service.approved_call,
        gate="mcp",
        risk="destructive",
    )
