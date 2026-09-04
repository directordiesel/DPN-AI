from __future__ import annotations

from typing import Any


SYSTEM_TYPES = {
    "http": {"capabilities": ["connector_discovery", "http_request", "vault_secret_resolution"], "tool_hints": ["list_connectors", "connector_request"]},
    "mcp": {"capabilities": ["mcp_discovery", "mcp_allowlist", "mcp_tool_call"], "tool_hints": ["mcp_status", "list_mcp_servers", "discover_mcp_tools", "call_mcp_tool"]},
    "github": {"capabilities": ["repository_read", "repository_write", "issue_pr_workflows"], "tool_hints": ["discover_tools"]},
    "database": {"capabilities": ["structured_query", "schema_awareness", "transaction_safety"], "tool_hints": ["discover_tools"]},
    "api": {"capabilities": ["connector_discovery", "http_request", "credential_reference"], "tool_hints": ["list_connectors", "connector_request"]},
    "webhook": {"capabilities": ["event_intake", "signature_validation", "idempotency"], "tool_hints": ["discover_tools"]},
    "filesystem": {"capabilities": ["workspace_io", "provenance"], "tool_hints": ["list_files", "read_file", "write_file"]},
}

ALIASES = {
    "rest": "api", "graphql": "api", "web": "http", "connector": "http",
    "model-context-protocol": "mcp", "repo": "github", "git": "github", "sql": "database",
}

MODES = {"inspect", "plan", "execute", "sync", "migrate", "monitor", "repair"}


def _normalize_system(value: str) -> str:
    item = str(value or "").strip().lower()
    return ALIASES.get(item, item)


def build_connector_orchestration_plan(
    objective: str,
    systems: list[str] | None = None,
    mode: str = "plan",
    allow_external_actions: bool = False,
    require_approval_for_writes: bool = True,
    max_operations: int = 50,
    require_idempotency: bool = True,
) -> dict[str, Any]:
    normalized_mode = str(mode or "plan").strip().lower()
    if normalized_mode not in MODES:
        normalized_mode = "plan"
    normalized_systems: list[str] = []
    for item in systems or ["http", "mcp"]:
        value = _normalize_system(item)
        if value in SYSTEM_TYPES and value not in normalized_systems:
            normalized_systems.append(value)
    if not normalized_systems:
        normalized_systems = ["http"]
    operation_cap = max(1, min(int(max_operations), 200))

    capabilities: list[str] = []
    tool_hints: list[str] = []
    for system in normalized_systems:
        capabilities.extend(SYSTEM_TYPES[system]["capabilities"])
        tool_hints.extend(SYSTEM_TYPES[system]["tool_hints"])

    stages = [
        {"id": "inventory", "goal": "Discover configured connectors, MCP servers, available tools, scopes, credentials references, and current policy before any call."},
        {"id": "classify_actions", "goal": "Classify each planned action as read, write, destructive, credential-dependent, external, or local-only."},
        {"id": "build_data_contracts", "goal": "Define input/output schemas, identifier mapping, provenance, validation, idempotency keys, and conflict strategy."},
        {"id": "permission_gate", "goal": "Re-read live permissions and approval state before every protected or external action; persisted plans are never authorization."},
        {"id": "dry_run", "goal": "Validate routes, allowlists, schemas, targets, and expected side effects before write execution."},
        {"id": "execute", "goal": "Execute bounded operations with exact target/result evidence and stop immediately on revoked permission, missing credential, or policy failure."},
        {"id": "verify", "goal": "Read back or otherwise verify externally observable state; do not treat request submission as success proof."},
        {"id": "reconcile", "goal": "Detect partial success, duplicates, drift, stale mappings, conflicts, or inconsistent cross-system state and produce bounded repair actions."},
        {"id": "audit", "goal": "Record systems touched, actual tools/endpoints, operation counts, approvals, outputs, failures, redacted credential references, and unresolved state."},
    ]
    if normalized_mode == "monitor":
        stages.insert(5, {"id": "baseline", "goal": "Capture an evidence-backed baseline and change conditions; do not claim monitoring is active without scheduler evidence."})
    if normalized_mode == "migrate":
        stages.insert(4, {"id": "migration_map", "goal": "Map source IDs to destination IDs, compatibility gaps, rollback boundaries, ordering constraints, and reconciliation checks."})

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "mode": normalized_mode,
        "systems": normalized_systems,
        "required_capabilities": list(dict.fromkeys(capabilities)),
        "preferred_tool_hints": list(dict.fromkeys(tool_hints)),
        "limits": {"max_operations": operation_cap},
        "quality_gates": [
            "configured_systems_discovered", "live_authorization_checked", "secret_values_not_persisted",
            "side_effects_classified", "schemas_validated", "external_state_verified", "partial_failure_reconciled",
            "actual_operations_audited",
        ],
        "execution_policy": {
            "external_actions_allowed": bool(allow_external_actions),
            "writes_require_approval": bool(require_approval_for_writes),
            "idempotency_required": bool(require_idempotency),
            "persisted_configuration_is_not_authorization": True,
            "recheck_live_policy_before_each_protected_action": True,
            "secret_values_must_use_vault_references": True,
            "never_log_plaintext_secrets": True,
            "mcp_tools_must_be_discovered_before_allowlisting": True,
            "mcp_calls_must_be_allowlisted": True,
            "http_connectors_must_remain_host_and_method_bounded": True,
            "redirect_or_host_escape_must_not_be_followed": True,
            "no_silent_cross_system_partial_success": True,
            "write_success_requires_readback_or_equivalent_evidence": True,
            "operator_cancellation_is_terminal": True,
            "external_side_effects_require_policy_approval": True,
        },
        "stages": stages,
    }


def register(registry) -> None:
    registry.register(
        name="plan_connector_orchestration",
        description="Plan safe multi-system connector, MCP, API, GitHub, database, webhook, and workspace operations with live authorization, idempotency, reconciliation, and audit evidence.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "systems": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "allow_external_actions": {"type": "boolean", "default": False},
                "require_approval_for_writes": {"type": "boolean", "default": True},
                "max_operations": {"type": "integer", "default": 50},
                "require_idempotency": {"type": "boolean", "default": True},
            },
            "required": ["objective"],
        },
        function=build_connector_orchestration_plan,
        risk="read",
    )
