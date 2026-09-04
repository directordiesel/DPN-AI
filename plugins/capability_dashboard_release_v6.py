from __future__ import annotations

from typing import Any


CAPABILITY_DOMAINS = [
    "models", "tools", "skills", "coding", "documents", "images", "vision", "research", "repository",
    "multimodal", "memory", "missions", "automation", "connectors", "mcp", "browser", "desktop", "voice",
    "media", "sandbox", "security", "recovery"
]

RELEASE_GATES = [
    "ci_success", "security_gate_success", "runtime_recovery_success", "regression_suite_success",
    "no_known_critical_security_findings", "draft_pr_reviewed", "documentation_current", "main_unchanged_until_merge"
]


def build_capability_dashboard_plan(
    objective: str = "Assess DPN AI v6 readiness",
    domains: list[str] | None = None,
    require_all_release_gates: bool = True,
    include_degraded_capabilities: bool = True,
    max_findings: int = 200,
) -> dict[str, Any]:
    selected: list[str] = []
    for item in domains or CAPABILITY_DOMAINS:
        value = str(item or "").strip().lower()
        if value in CAPABILITY_DOMAINS and value not in selected:
            selected.append(value)
    if not selected:
        selected = list(CAPABILITY_DOMAINS)
    finding_cap = max(1, min(int(max_findings), 500))

    return {
        "ok": True,
        "objective": str(objective or "").strip(),
        "domains": selected,
        "limits": {"max_findings": finding_cap},
        "release_gates": list(RELEASE_GATES),
        "quality_gates": [
            "capabilities_derived_from_observable_status", "unavailable_and_degraded_capabilities_visible",
            "actual_model_provider_status_visible", "security_and_permission_state_visible",
            "background_job_and_recovery_state_visible", "release_gate_evidence_attached", "no_false_ready_state"
        ],
        "execution_policy": {
            "all_release_gates_required": bool(require_all_release_gates),
            "include_degraded_capabilities": bool(include_degraded_capabilities),
            "do_not_mark_ready_with_pending_checks": True,
            "do_not_mark_ready_with_failed_checks": True,
            "do_not_hide_missing_optional_dependencies": True,
            "do_not_treat_configured_as_healthy": True,
            "do_not_treat_tool_registration_as_runtime_success": True,
            "main_must_remain_unchanged_until_merge": True,
            "pr_must_remain_draft_until_release_ready": True,
            "merge_requires_explicit_user_authorization": True,
            "security_controls_must_not_be_weakened_for_release": True,
            "tests_must_not_be_deleted_or_relaxed_to_force_green": True
        },
        "stages": [
            {"id": "inventory", "goal": "Inventory v6 capabilities, registered tools, skills, providers, optional dependencies, connectors, background services, and generated artifacts."},
            {"id": "runtime_status", "goal": "Collect observable runtime health for model providers, media/voice, browser, desktop, MCP, sandbox, connectors, memory, jobs, and recovery surfaces."},
            {"id": "capability_matrix", "goal": "Classify each capability as available, degraded, unavailable, blocked-by-policy, or not-configured with evidence and remediation."},
            {"id": "integration_audit", "goal": "Trace handoffs among Universal Creator, router, specialists, memory, recovery, automation, connectors, previews, and vision; surface duplicate or conflicting orchestration."},
            {"id": "security_audit", "goal": "Confirm workspace, command, browser/network, secret/vault, MCP allowlist, connector, model-provider, approval, and persistence boundaries remain intact."},
            {"id": "validation_audit", "goal": "Collect exact CI, Security Gate, Runtime & Recovery, regression, artifact-validation, and package evidence for the current head."},
            {"id": "documentation_audit", "goal": "Verify README/release notes and capability documentation match what the current branch actually supports."},
            {"id": "release_decision", "goal": "Return ready/not-ready from evidence only, listing failed, blocked, pending, degraded, and informational findings separately."},
            {"id": "handoff", "goal": "Produce final release checklist, exact head/base SHAs, PR state, remaining blockers, and the next safe action without merging automatically."}
        ]
    }


def evaluate_release_gates(gates: dict[str, Any], require_all: bool = True) -> dict[str, Any]:
    normalized = {name: bool(gates.get(name, False)) for name in RELEASE_GATES}
    missing = [name for name, passed in normalized.items() if not passed]
    ready = not missing if require_all else sum(normalized.values()) >= max(1, len(RELEASE_GATES) - 1)
    return {
        "ok": True,
        "ready": ready,
        "gates": normalized,
        "missing": missing,
        "policy": {"require_all": bool(require_all), "no_pending_or_unknown_gate_counts_as_pass": True}
    }


def register(registry) -> None:
    registry.register(
        name="plan_capability_dashboard_release",
        description="Plan a full DPN AI v6 capability dashboard, integration audit, and evidence-backed release-readiness decision without weakening gates or merging automatically.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "default": "Assess DPN AI v6 readiness"},
                "domains": {"type": "array", "items": {"type": "string"}},
                "require_all_release_gates": {"type": "boolean", "default": True},
                "include_degraded_capabilities": {"type": "boolean", "default": True},
                "max_findings": {"type": "integer", "default": 200}
            }
        },
        function=build_capability_dashboard_plan,
        risk="read"
    )
    registry.register(
        name="evaluate_v6_release_gates",
        description="Evaluate the fixed DPN AI v6 release gates; unknown or absent gates do not count as passing.",
        parameters={
            "type": "object",
            "properties": {
                "gates": {"type": "object"},
                "require_all": {"type": "boolean", "default": True}
            },
            "required": ["gates"]
        },
        function=evaluate_release_gates,
        risk="read"
    )
