from __future__ import annotations

from app.connector_governance_v9 import ConnectorGovernanceV9


_RUNTIME = ConnectorGovernanceV9()


def plan_external_operation_v9(
    system: str,
    operation: str,
    target_id: str,
    action: str,
    max_operations: int = 25,
    allowed_actions: list[str] | None = None,
    discovered_actions: list[str] | None = None,
    approval_present: bool = False,
    idempotency_key: str | None = None,
):
    return _RUNTIME.build_request(
        system,
        operation,
        target_id,
        action,
        max_operations=max_operations,
        allowed_actions=allowed_actions,
        discovered_actions=discovered_actions,
        approval_present=approval_present,
        idempotency_key=idempotency_key,
    )


def evaluate_external_completion_v9(evidence: dict | None = None, write_expected: bool = False):
    return _RUNTIME.evaluate_completion(evidence, write_expected=write_expected)


def register(registry) -> None:
    registry.register(
        name="plan_external_operation_v9",
        description="Validate a bounded connector or MCP operation against discovered actions, allowlists, approval requirements, and idempotency policy before using the hardened live adapter.",
        parameters={
            "type": "object",
            "properties": {
                "system": {"type": "string", "enum": ["connector", "mcp"]},
                "operation": {"type": "string", "enum": ["inspect", "read", "write", "delete", "sync", "execute"]},
                "target_id": {"type": "string", "minLength": 1},
                "action": {"type": "string", "minLength": 1},
                "max_operations": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                "allowed_actions": {"type": "array", "items": {"type": "string"}, "default": []},
                "discovered_actions": {"type": "array", "items": {"type": "string"}, "default": []},
                "approval_present": {"type": "boolean", "default": False},
                "idempotency_key": {"type": ["string", "null"], "default": None}
            },
            "required": ["system", "operation", "target_id", "action"],
            "additionalProperties": False
        },
        function=plan_external_operation_v9,
        risk="read",
    )
    registry.register(
        name="evaluate_external_completion_v9",
        description="Evaluate connector/MCP completion evidence and fail closed when discovery, allowlist, live-policy, approval, reconciliation, secret-safety, or write-verification evidence is missing.",
        parameters={
            "type": "object",
            "properties": {
                "evidence": {"type": "object", "default": {}},
                "write_expected": {"type": "boolean", "default": False}
            },
            "additionalProperties": False
        },
        function=evaluate_external_completion_v9,
        risk="read",
    )
