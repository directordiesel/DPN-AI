from __future__ import annotations

from typing import Any

DOMAINS = {
    "dependencies", "secrets", "permissions", "auth", "api", "filesystem", "network",
    "plugins", "connectors", "mcp", "models", "memory", "automation", "desktop", "mobile",
    "packaging", "installer", "updates", "recovery", "versioning", "tests", "performance"
}


def build_security_qa_plan(
    objective: str,
    domains: list[str] | None = None,
    require_cross_platform: bool = True,
    require_release_consistency: bool = True,
    max_findings: int = 200,
) -> dict[str, Any]:
    selected: list[str] = []
    for item in domains or [
        "dependencies", "secrets", "permissions", "auth", "api", "filesystem", "network",
        "plugins", "connectors", "mcp", "memory", "automation", "desktop", "packaging",
        "updates", "recovery", "versioning", "tests", "performance"
    ]:
        value = str(item or "").strip().lower()
        if value in DOMAINS and value not in selected:
            selected.append(value)
    if not selected:
        selected = ["tests"]
    finding_cap = max(20, min(int(max_findings), 500))
    return {
        "ok": bool(str(objective or "").strip()),
        "objective": str(objective or "").strip(),
        "domains": selected,
        "limits": {"max_findings": finding_cap},
        "stages": [
            {"id": "inventory", "goal": "Inventory runtime surfaces, trust boundaries, external integrations, storage, packaging, tests, and release metadata."},
            {"id": "threat_model", "goal": "Map assets, actors, entry points, privilege boundaries, sensitive data, local/remote exposure, and abuse cases."},
            {"id": "static_review", "goal": "Inspect source, manifests, workflows, dependency metadata, secrets handling, auth, path/network controls, and dangerous primitives."},
            {"id": "runtime_review", "goal": "Exercise safe runtime checks for auth boundaries, API behavior, cancellation, recovery, persistence, and failure handling."},
            {"id": "cross_platform", "goal": "Validate Windows/Linux behavior and future desktop/mobile boundaries where supported without assuming parity that has not been tested."},
            {"id": "version_consistency", "goal": "Compare VERSION, runtime API version, UI branding, package metadata, installer/update metadata, and release documentation."},
            {"id": "negative_tests", "goal": "Test denied/invalid inputs, missing permissions, stale credentials, malformed payloads, unsupported files, network loss, and partial failures."},
            {"id": "performance", "goal": "Check startup, memory, CPU, queue pressure, indexing, model loading, and bounded resource behavior."},
            {"id": "repair", "goal": "Apply minimal safe fixes; never disable controls, skip tests, or broaden permissions to make checks pass."},
            {"id": "verify", "goal": "Re-run affected tests and independent security/QA gates after every repair and preserve evidence."},
            {"id": "release_assessment", "goal": "Classify blockers, unresolved risks, known limitations, and exact evidence required before release readiness."},
        ],
        "quality_gates": [
            "dependency_audit_complete", "secret_scan_complete", "auth_boundaries_verified",
            "path_and_network_controls_verified", "dangerous_writes_approval_gated", "negative_tests_run",
            "runtime_recovery_verified", "version_metadata_consistent", "no_test_weakening",
            "no_security_control_bypass", "critical_findings_resolved", "known_risks_documented",
            "release_claims_backed_by_evidence"
        ],
        "execution_policy": {
            "require_cross_platform": bool(require_cross_platform),
            "require_release_consistency": bool(require_release_consistency),
            "never_weaken_tests_to_pass": True,
            "never_disable_security_controls_to_pass": True,
            "never_broaden_permissions_without_explicit_reason_and_review": True,
            "fail_closed_on_unknown_authorization": True,
            "secrets_must_not_be_logged_or_committed": True,
            "external_writes_require_existing_approval_policy": True,
            "version_source_of_truth_must_be_single_and_consistent": True,
            "repairs_require_reverification": True,
            "critical_or_high_unresolved_findings_block_release": True,
        },
    }


def evaluate_security_qa_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    required = [
        "dependency_audit", "secret_scan", "auth_tests", "negative_tests", "runtime_tests",
        "version_check", "test_results", "security_results"
    ]
    missing = [key for key in required if not evidence.get(key)]
    findings = list(evidence.get("findings") or [])
    blockers = [f for f in findings if str(f.get("severity", "")).lower() in {"critical", "high"} and not f.get("resolved")]
    weakened = bool(evidence.get("tests_weakened") or evidence.get("security_controls_disabled"))
    return {
        "ok": not missing and not blockers and not weakened,
        "missing_evidence": missing,
        "release_blockers": blockers,
        "tests_or_controls_weakened": weakened,
        "completion_allowed": not missing and not blockers and not weakened,
    }


def register(registry) -> None:
    registry.register(
        name="plan_security_qa_v7",
        description="Plan comprehensive DPN AI v7 security and QA across source, runtime, integrations, packaging, recovery, version consistency, negative tests, and release readiness.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "domains": {"type": "array", "items": {"type": "string"}},
                "require_cross_platform": {"type": "boolean", "default": True},
                "require_release_consistency": {"type": "boolean", "default": True},
                "max_findings": {"type": "integer", "default": 200}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_security_qa_plan,
        risk="read"
    )
    registry.register(
        name="evaluate_security_qa_evidence_v7",
        description="Evaluate security/QA evidence and block completion when required evidence is missing, high-severity findings remain, or tests/security controls were weakened.",
        parameters={"type": "object", "properties": {"evidence": {"type": "object"}}, "required": ["evidence"]},
        function=evaluate_security_qa_evidence,
        risk="read"
    )
