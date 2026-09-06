from __future__ import annotations

from app.dpn_http_connector_adapter_v10 import HTTPConnectorProtocolService


def register(registry) -> None:
    service = HTTPConnectorProtocolService(registry.db, registry.connectors)

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
        description="Execute a least-privilege DPN Connector Protocol read/search through the hardened connector transport.",
        parameters={
            "type": "object",
            "properties": {
                "connector_id": {"type": "string"},
                "path": {"type": "string", "default": ""},
                "params": {"type": ["object", "null"], "default": None},
                "timeout_seconds": {"type": "integer", "default": 30},
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
        description="Execute an explicitly human-approved DPN Connector Protocol create, update, or delete operation. This tool is always single-use approval gated.",
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
