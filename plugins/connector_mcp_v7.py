from __future__ import annotations

from typing import Any


SYSTEMS = {"http", "api", "mcp", "github", "database", "webhook", "filesystem", "email", "calendar", "storage", "chat"}
MODES = {"inspect", "plan", "execute", "sync", "migrate", "monitor", "repair"}
ALIASES = {"rest": "api", "graphql": "api", "model-context-protocol": "mcp", "repo": "github", "git": "github", "sql": "database", "drive": "storage"}


def _normalize_system(value: str) -> str:
    item = str(value or "").strip().lower()
    return ALIASES.get(item, item)


def build_connector_mcp_v7_plan(
    objective: str,
    systems: list[str] | None = None,
    mode: str = "plan",
    allow_external_actions: bool = False,
    require_approval_for_writes: bool = True,
    max_operations: int = 50,
    require_idempotency: bool = True,
) -> dict[str, Any]:
    objective = str(objective or "").strip()
    normalized_mode = str(mode or "plan").strip().lower()
    if normalized_mode not in MODES:
        normalized_mode = "plan"
    selected: list[str] = []
    for raw in systems or ["mcp", "api"]:
        item = _normalize_system(raw)
        if item in SYSTEMS and item not in selected:
            selected.append(item)
    if not selected:
        selected = ["api"]
    operation_cap = max(1, min(int(max_operations), 200))

    stages = [
        {"id": "inventory", "goal": "Discover configured connectors, MCP servers, tool schemas, account scopes, credential references, and live policy before any operation."},
        {"id": "capability_map", "goal": "Map each requested action to one exact connector/tool and required scope; reject capability assumptions that were not discovered."},
        {"id": "classify", "goal": "Classify actions as read, write, destructive, credential-sensitive, external, or local-only and identify approval boundaries."},
        {"id": "contract", "goal": "Validate tool input/output schemas, identifiers, provenance, idempotency keys, pagination, retry semantics, and conflict handling."},
        {"id": "permission_gate", "goal": "Re-check live permissions immediately before each protected action; stored plans, previous approvals, and cached scopes are never authorization."},
        {"id": "dry_run", "goal": "Resolve exact targets and expected effects without executing writes; block ambiguous recipients, repositories, files, endpoints, or accounts."},
        {"id": "execute", "goal": "Execute only bounded approved operations and stop on revoked permissions, schema mismatch, credential failure, host escape, or policy failure."},
        {"id": "verify", "goal": "Read back or independently verify externally observable state. Request submission alone is not completion evidence."},
        {"id": "reconcile", "goal": "Detect partial success, duplicates, stale mappings, pagination gaps, drift, conflicts, and inconsistent cross-system state before retrying."},
        {"id": "audit", "goal": "Record actual systems/tools, operation IDs, redacted credential references, approvals, outputs, failures, retries, and unresolved state without plaintext secrets."},
    ]
    if normalized_mode == "monitor":
        stages.insert(6, {"id": "baseline", "goal": "Capture a comparison baseline and trigger criteria; recurring execution must be delegated to the scheduler."})
    if normalized_mode == "migrate":
        stages.insert(5, {"id": "migration_map", "goal": "Map source IDs to destination IDs, ordering constraints, compatibility gaps, rollback boundaries, and reconciliation checks."})

    return {
        "ok": bool(objective),
        "objective": objective,
        "mode": normalized_mode,
        "systems": selected,
        "limits": {"max_operations": operation_cap},
        "required_capabilities": ["connector_discovery", "mcp_discovery", "schema_validation", "live_authorization", "idempotency", "verification", "audit_provenance"],
        "quality_gates": [
            "configured_systems_discovered",
            "tool_schemas_discovered",
            "live_authorization_checked",
            "secret_values_not_persisted",
            "side_effects_classified",
            "ambiguous_targets_rejected",
            "external_state_verified",
            "partial_failures_reconciled",
            "actual_operations_audited",
        ],
        "execution_policy": {
            "external_actions_allowed": bool(allow_external_actions),
            "writes_require_approval": bool(require_approval_for_writes),
            "idempotency_required": bool(require_idempotency),
            "persisted_configuration_is_not_authorization": True,
            "cached_scope_is_not_authorization": True,
            "recheck_live_policy_before_each_protected_action": True,
            "secret_values_must_use_vault_or_connector_references": True,
            "never_log_plaintext_secrets": True,
            "mcp_servers_and_tools_must_be_discovered_before_use": True,
            "mcp_calls_must_be_allowlisted": True,
            "connector_host_method_and_scope_bounds_must_be_enforced": True,
            "redirect_or_host_escape_must_not_be_followed": True,
            "ambiguous_external_targets_require_resolution_before_write": True,
            "no_silent_cross_system_partial_success": True,
            "write_success_requires_readback_or_equivalent_evidence": True,
            "pagination_must_be_completed_or_disclosed": True,
            "operator_cancellation_is_terminal": True,
            "external_side_effects_require_policy_approval": True,
            "monitoring_requires_scheduler_evidence": True,
        },
        "stages": stages,
    }


def evaluate_connector_evidence_v7(evidence: dict[str, Any] | None, writes_expected: bool = False) -> dict[str, Any]:
    evidence = dict(evidence or {})
    operations = evidence.get("operations") or []
    failures: list[str] = []

    if not evidence.get("discovery_complete"):
        failures.append("connector_or_tool_discovery_missing")
    if not evidence.get("authorization_checked"):
        failures.append("live_authorization_missing")
    if evidence.get("plaintext_secret_detected"):
        failures.append("plaintext_secret_detected")
    if evidence.get("ambiguous_target_detected"):
        failures.append("ambiguous_target_detected")
    if evidence.get("partial_failure_unreconciled"):
        failures.append("partial_failure_unreconciled")
    if evidence.get("pagination_incomplete") and not evidence.get("pagination_limit_disclosed"):
        failures.append("pagination_incomplete_undisclosed")

    valid_operations = []
    for item in operations:
        if not isinstance(item, dict):
            continue
        if item.get("system") and item.get("tool") and item.get("status"):
            valid_operations.append(item)

    if writes_expected:
        writes = [item for item in valid_operations if item.get("write")]
        if not writes:
            failures.append("expected_write_evidence_missing")
        elif any(not item.get("verified") for item in writes):
            failures.append("write_readback_verification_missing")
        if any(item.get("approval_required") and not item.get("approval_evidence") for item in writes):
            failures.append("write_approval_evidence_missing")

    return {
        "ok": not failures,
        "failures": failures,
        "operation_count": len(valid_operations),
        "completion_allowed": not failures,
    }


def register(registry) -> None:
    registry.register(
        name="plan_connector_mcp_v7",
        description="Plan safe Connector/MCP v7 operations with discovery, schema validation, live authorization, exact-target resolution, idempotency, verification, reconciliation, and secret-safe audit evidence.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "systems": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": sorted(MODES), "default": "plan"},
                "allow_external_actions": {"type": "boolean", "default": False},
                "require_approval_for_writes": {"type": "boolean", "default": True},
                "max_operations": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "require_idempotency": {"type": "boolean", "default": True}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_connector_mcp_v7_plan,
        risk="read",
    )
    registry.register(
        name="evaluate_connector_evidence_v7",
        description="Evaluate Connector/MCP v7 completion evidence, including discovery, live authorization, secret safety, exact targets, reconciliation, approvals, pagination, and write verification.",
        parameters={
            "type": "object",
            "properties": {
                "evidence": {"type": "object"},
                "writes_expected": {"type": "boolean", "default": False}
            },
            "required": ["evidence"],
            "additionalProperties": False
        },
        function=evaluate_connector_evidence_v7,
        risk="read",
    )
