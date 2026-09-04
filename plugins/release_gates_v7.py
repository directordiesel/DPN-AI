from __future__ import annotations

from typing import Any

REQUIRED_GATES = [
    "version_consistency",
    "unit_tests",
    "integration_tests",
    "security_gate",
    "runtime_recovery",
    "dependency_review",
    "secret_scan",
    "permission_boundary_review",
    "artifact_integrity",
    "release_notes",
]


def build_release_gate_plan(version: str, target_branch: str = "main") -> dict[str, Any]:
    return {
        "ok": bool(str(version or "").strip()),
        "version": str(version or "").strip(),
        "target_branch": str(target_branch or "main").strip(),
        "required_gates": list(REQUIRED_GATES),
        "policy": {
            "all_required_gates_must_pass": True,
            "unknown_gate_state_blocks_release": True,
            "critical_or_high_security_findings_block_release": True,
            "failed_tests_block_release": True,
            "version_mismatch_blocks_release": True,
            "test_weakening_forbidden": True,
            "security_control_weakening_forbidden": True,
            "merge_requires_explicit_authorization": True,
            "release_evidence_must_match_candidate_head": True,
            "stale_green_checks_do_not_authorize_new_head": True,
        },
    }


def evaluate_release_candidate(evidence: dict[str, Any]) -> dict[str, Any]:
    gate_results = dict(evidence.get("gates") or {})
    missing = [gate for gate in REQUIRED_GATES if gate not in gate_results]
    failed = [gate for gate, status in gate_results.items() if gate in REQUIRED_GATES and status != "pass"]
    blockers = list(evidence.get("blockers") or [])
    high_findings = list(evidence.get("critical_or_high_findings") or [])
    test_weakened = bool(evidence.get("tests_weakened"))
    security_weakened = bool(evidence.get("security_controls_weakened"))
    head_matches = bool(evidence.get("evidence_matches_candidate_head"))

    release_ready = not any([
        missing, failed, blockers, high_findings, test_weakened, security_weakened, not head_matches
    ])
    return {
        "ok": release_ready,
        "release_ready": release_ready,
        "missing_gates": missing,
        "failed_gates": failed,
        "blockers": blockers,
        "critical_or_high_findings": high_findings,
        "tests_weakened": test_weakened,
        "security_controls_weakened": security_weakened,
        "evidence_matches_candidate_head": head_matches,
        "merge_allowed_by_gates": release_ready,
    }


def register(registry) -> None:
    registry.register(
        name="plan_release_gates_v7",
        description="Plan DPN AI v7 release-candidate validation with strict version, test, security, runtime, dependency, secret, permission, artifact, and release-note gates.",
        parameters={
            "type": "object",
            "properties": {
                "version": {"type": "string", "minLength": 1},
                "target_branch": {"type": "string", "default": "main"}
            },
            "required": ["version"],
            "additionalProperties": False
        },
        function=build_release_gate_plan,
        risk="read"
    )
    registry.register(
        name="evaluate_release_candidate_v7",
        description="Evaluate whether every required DPN AI v7 release gate passed for the exact candidate head.",
        parameters={"type": "object", "properties": {"evidence": {"type": "object"}}, "required": ["evidence"]},
        function=evaluate_release_candidate,
        risk="read"
    )
