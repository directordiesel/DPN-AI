from __future__ import annotations

from typing import Any


_CHANGE_KINDS = {"create", "update", "delete", "rename", "test", "config", "docs"}


def build_repository_change_plan(
    objective: str,
    affected_files: list[dict[str, Any]] | None = None,
    test_targets: list[str] | None = None,
    risk_level: str = "medium",
    max_files: int = 24,
) -> dict[str, Any]:
    objective = str(objective or "").strip()
    if not objective:
        return {"ok": False, "error": "objective is required"}

    risk = str(risk_level or "medium").strip().lower()
    if risk not in {"low", "medium", "high", "critical"}:
        risk = "medium"
    file_budget = max(1, min(int(max_files), 100))

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in affected_files or []:
        path = str(item.get("path") or "").strip()
        if not path or path in seen or len(normalized) >= file_budget:
            continue
        seen.add(path)
        kind = str(item.get("kind") or "update").strip().lower()
        if kind not in _CHANGE_KINDS:
            kind = "update"
        normalized.append(
            {
                "path": path,
                "kind": kind,
                "reason": str(item.get("reason") or "").strip(),
                "depends_on": [str(v).strip() for v in item.get("depends_on", []) if str(v).strip()][:20],
            }
        )

    tests = [str(item).strip() for item in (test_targets or []) if str(item).strip()][:50]
    destructive = [item["path"] for item in normalized if item["kind"] in {"delete", "rename"}]

    phases = [
        {"name": "repository_map", "purpose": "Trace entry points, manifests, ownership boundaries, imports, exports, tests, and configuration before editing."},
        {"name": "impact_analysis", "purpose": "Determine direct and transitive impact for proposed files and reject edits not connected to the objective."},
        {"name": "change_set", "purpose": "Order the smallest coherent multi-file change set so dependencies are modified before dependents."},
        {"name": "implementation", "purpose": "Apply focused edits while preserving architecture and existing security controls."},
        {"name": "targeted_validation", "purpose": "Run checks closest to changed components before broad regression tests."},
        {"name": "regression_validation", "purpose": "Run the relevant repository test/build/security suite and record command evidence."},
        {"name": "diff_review", "purpose": "Review final diff for scope creep, dead code, regressions, missing tests, unsafe permissions, and accidental secret exposure."},
        {"name": "completion_gate", "purpose": "Complete only when objective criteria and required checks have passing evidence."},
    ]

    return {
        "ok": True,
        "engine": "dpn-autonomous-coding-v7",
        "objective": objective,
        "risk_level": risk,
        "file_budget": file_budget,
        "changes": normalized,
        "test_targets": tests,
        "destructive_paths": destructive,
        "approval_required": bool(destructive or risk in {"high", "critical"}),
        "execution_policy": {
            "map_repository_before_editing": True,
            "trace_transitive_impact": True,
            "minimal_change_set": True,
            "exact_edits_preferred": True,
            "snapshot_before_broad_change": True,
            "no_unapproved_destructive_edits": True,
            "no_implicit_dependency_installs": True,
            "no_test_weakening": True,
            "no_security_gate_bypass": True,
            "require_test_evidence": True,
            "require_final_diff_review": True,
        },
        "phases": phases,
    }


def evaluate_coding_evidence(
    checks: list[dict[str, Any]] | None = None,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    normalized_checks: list[dict[str, Any]] = []
    passing = True
    for item in list(checks or [])[:100]:
        name = str(item.get("name") or item.get("command") or "").strip()
        status = str(item.get("status") or "unknown").strip().lower()
        evidence = item.get("evidence")
        passed = status in {"passed", "success", "complete"} and bool(evidence)
        normalized_checks.append({"name": name, "status": status, "evidence": evidence, "passed": passed})
        if not passed:
            passing = False

    files = [str(path).strip() for path in (changed_files or []) if str(path).strip()][:100]
    if not normalized_checks or not files:
        passing = False

    return {
        "ok": True,
        "ready": passing,
        "checks": normalized_checks,
        "changed_files": files,
        "failed_or_unverified": [item["name"] for item in normalized_checks if not item["passed"]],
        "policy": "Autonomous coding completion requires changed-file evidence plus explicit passing validation evidence.",
    }


def register(registry):
    registry.register(
        name="plan_repository_change_v7",
        description="Plan a bounded repository-aware multi-file coding change with impact analysis, validation, destructive-change approval, and final diff review.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "affected_files": {"type": "array", "items": {"type": "object"}, "default": []},
                "test_targets": {"type": "array", "items": {"type": "string"}, "default": []},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 100, "default": 24}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_repository_change_plan,
        risk="read",
    )
    registry.register(
        name="evaluate_coding_evidence_v7",
        description="Verify that an autonomous coding mission has changed-file evidence and explicit passing validation evidence before completion.",
        parameters={
            "type": "object",
            "properties": {
                "checks": {"type": "array", "items": {"type": "object"}, "default": []},
                "changed_files": {"type": "array", "items": {"type": "string"}, "default": []}
            },
            "additionalProperties": False
        },
        function=evaluate_coding_evidence,
        risk="read",
    )
