from __future__ import annotations

from typing import Any


_MODES = {"map", "impact", "review", "triage", "health", "release"}
_DEPTHS = {"quick", "standard", "deep"}


def _risk_band(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def build_repository_intelligence_plan(
    objective: str,
    mode: str = "map",
    depth: str = "standard",
    changed_files: list[str] | None = None,
    issue_or_pr_ref: str | None = None,
    require_dependency_graph: bool = True,
    require_regression_analysis: bool = True,
    max_files: int = 500,
) -> dict[str, Any]:
    mode = str(mode or "map").strip().lower()
    depth = str(depth or "standard").strip().lower()
    if mode not in _MODES:
        mode = "map"
    if depth not in _DEPTHS:
        depth = "standard"

    files = [str(item).strip() for item in (changed_files or []) if str(item).strip()]
    max_files = max(25, min(int(max_files), 5000))

    depth_profile = {
        "quick": {"max_files": min(max_files, 150), "trace_depth": 1, "cross_checks": 1},
        "standard": {"max_files": min(max_files, 750), "trace_depth": 3, "cross_checks": 2},
        "deep": {"max_files": max_files, "trace_depth": 6, "cross_checks": 3},
    }[depth]

    stages: list[dict[str, Any]] = [
        {
            "name": "inventory",
            "purpose": "Inspect repository tree, manifests, entry points, configuration, tests, workflows, generated/vendor boundaries, and package metadata before conclusions.",
            "preferred_tools": ["directory_tree", "list_files", "read_file", "search_text"],
        },
        {
            "name": "architecture_map",
            "purpose": "Identify components, ownership boundaries, entry points, shared services, public interfaces, state stores, and execution paths.",
            "outputs": ["component_map", "entry_points", "ownership_boundaries"],
        },
    ]

    if require_dependency_graph:
        stages.append(
            {
                "name": "dependency_graph",
                "purpose": "Trace imports, calls, events, configuration references, manifests, exports, and package dependencies; distinguish direct evidence from inferred edges.",
                "trace_depth": depth_profile["trace_depth"],
                "outputs": ["dependency_edges", "high_centrality_components", "unknown_edges"],
            }
        )

    if mode in {"impact", "review", "release"} or files:
        stages.append(
            {
                "name": "change_impact",
                "purpose": "Map changed files to upstream callers, downstream consumers, tests, configuration, workflows, data contracts, and release surfaces.",
                "changed_files": files,
                "outputs": ["affected_components", "affected_tests", "behavioral_risks", "release_risks"],
            }
        )

    if mode == "review":
        stages.append(
            {
                "name": "diff_review",
                "purpose": "Review changed behavior rather than line count; detect authorization regressions, broken contracts, stale configuration, dead branches, duplicate logic, missing tests, and unsafe side effects.",
                "issue_or_pr_ref": issue_or_pr_ref,
            }
        )

    if mode == "triage":
        stages.append(
            {
                "name": "issue_triage",
                "purpose": "Classify the issue by type, severity, affected subsystem, likely ownership, reproducibility, missing evidence, and smallest safe next investigation.",
                "issue_or_pr_ref": issue_or_pr_ref,
                "outputs": ["category", "severity", "affected_subsystem", "evidence_gaps", "next_action"],
            }
        )

    if mode in {"health", "map", "release"}:
        stages.append(
            {
                "name": "repository_health",
                "purpose": "Look for stale/dead code, duplicate systems, orphan files, architectural drift, weak test coverage, risky permissions, obsolete configuration, packaging gaps, and maintainability hotspots.",
                "outputs": ["health_findings", "dead_code_candidates", "duplication_candidates", "maintenance_hotspots"],
            }
        )

    if require_regression_analysis or mode in {"impact", "review", "release"}:
        stages.append(
            {
                "name": "regression_risk",
                "purpose": "Score regression risk from centrality, blast radius, state/schema changes, auth/security impact, test coverage, workflow/config changes, and externally visible contracts.",
                "scoring": {
                    "central_shared_component": 20,
                    "state_or_schema_change": 20,
                    "security_or_authorization_change": 25,
                    "public_api_or_event_contract_change": 15,
                    "workflow_or_packaging_change": 10,
                    "missing_or_weak_tests": 10,
                },
                "score_range": [0, 100],
            }
        )

    stages.extend(
        [
            {
                "name": "validate",
                "purpose": "Cross-check findings against repository evidence and tests; do not label code dead, stale, or unused solely because a text search found no obvious reference.",
                "cross_checks": depth_profile["cross_checks"],
            },
            {
                "name": "deliver",
                "purpose": "Return an evidence-backed architecture/impact report with exact files, confidence, unresolved unknowns, prioritized fixes, and validation recommendations.",
            },
        ]
    )

    sample_scores = [0, 25, 50, 75]
    return {
        "ok": True,
        "objective": objective.strip(),
        "mode": mode,
        "depth": depth,
        "issue_or_pr_ref": issue_or_pr_ref,
        "changed_files": files,
        "limits": depth_profile,
        "required_capabilities": [
            "repository_inventory",
            "architecture_mapping",
            "dependency_analysis",
            "change_impact_analysis",
            "regression_analysis",
            "evidence_validation",
        ],
        "quality_gates": [
            "inventory_before_conclusion",
            "evidence_for_material_findings",
            "dependency_edges_are_labeled_observed_or_inferred",
            "impact_includes_tests_and_config",
            "dead_code_findings_require_cross_checks",
            "risk_scores_explain_contributing_factors",
        ],
        "risk_scale": {str(score): _risk_band(score) for score in sample_scores},
        "execution_policy": {
            "read_before_edit": True,
            "no_destructive_git_actions": True,
            "no_automatic_issue_or_pr_mutation": True,
            "do_not_claim_dead_code_from_single_search": True,
            "do_not_claim_safe_merge_without_validation_evidence": True,
            "separate_observed_dependencies_from_inferred_dependencies": True,
            "security_and_authorization_changes_raise_risk": True,
            "external_side_effects_require_policy_approval": True,
        },
        "stages": stages,
    }


def register(registry):
    registry.register(
        name="plan_repository_intelligence",
        description="Plan repository architecture mapping, dependency/change-impact analysis, PR review, issue triage, health audits, regression-risk assessment, or release readiness with evidence-first safeguards.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["map", "impact", "review", "triage", "health", "release"], "default": "map"},
                "depth": {"type": "string", "enum": ["quick", "standard", "deep"], "default": "standard"},
                "changed_files": {"type": "array", "items": {"type": "string"}, "default": []},
                "issue_or_pr_ref": {"type": ["string", "null"], "default": None},
                "require_dependency_graph": {"type": "boolean", "default": True},
                "require_regression_analysis": {"type": "boolean", "default": True},
                "max_files": {"type": "integer", "minimum": 25, "maximum": 5000, "default": 500}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_repository_intelligence_plan,
        risk="read",
    )
