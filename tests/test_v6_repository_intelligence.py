from __future__ import annotations

from plugins.repository_intelligence_v6 import build_repository_intelligence_plan


def _stage_names(plan: dict) -> list[str]:
    return [stage["name"] for stage in plan["stages"]]


def test_map_mode_builds_architecture_dependency_health_and_validation_stages():
    plan = build_repository_intelligence_plan("Map this repository", mode="map")
    names = _stage_names(plan)
    assert plan["mode"] == "map"
    assert "inventory" in names
    assert "architecture_map" in names
    assert "dependency_graph" in names
    assert "repository_health" in names
    assert "regression_risk" in names
    assert names[-2:] == ["validate", "deliver"]


def test_impact_mode_tracks_changed_files_and_tests_config_risk():
    plan = build_repository_intelligence_plan(
        "Assess impact",
        mode="impact",
        changed_files=["app/main.py", "app/db.py"],
    )
    assert plan["changed_files"] == ["app/main.py", "app/db.py"]
    impact = next(stage for stage in plan["stages"] if stage["name"] == "change_impact")
    assert "affected_tests" in impact["outputs"]
    assert "release_risks" in impact["outputs"]


def test_review_mode_includes_diff_review_and_pr_reference():
    plan = build_repository_intelligence_plan(
        "Review PR 24",
        mode="review",
        issue_or_pr_ref="#24",
    )
    review = next(stage for stage in plan["stages"] if stage["name"] == "diff_review")
    assert review["issue_or_pr_ref"] == "#24"
    assert plan["execution_policy"]["do_not_claim_safe_merge_without_validation_evidence"] is True


def test_triage_mode_includes_evidence_gaps_and_next_action():
    plan = build_repository_intelligence_plan(
        "Triage issue",
        mode="triage",
        issue_or_pr_ref="#101",
    )
    triage = next(stage for stage in plan["stages"] if stage["name"] == "issue_triage")
    assert "evidence_gaps" in triage["outputs"]
    assert "next_action" in triage["outputs"]


def test_depth_and_max_file_limits_are_bounded():
    quick = build_repository_intelligence_plan("Quick map", depth="quick", max_files=5000)
    deep = build_repository_intelligence_plan("Deep map", depth="deep", max_files=99999)
    assert quick["limits"]["max_files"] == 150
    assert quick["limits"]["trace_depth"] == 1
    assert deep["limits"]["max_files"] == 5000
    assert deep["limits"]["trace_depth"] == 6


def test_invalid_options_fall_back_safely():
    plan = build_repository_intelligence_plan("Inspect", mode="nonsense", depth="impossible")
    assert plan["mode"] == "map"
    assert plan["depth"] == "standard"


def test_dependency_graph_can_be_disabled_but_validation_remains():
    plan = build_repository_intelligence_plan(
        "Focused review",
        mode="review",
        require_dependency_graph=False,
    )
    names = _stage_names(plan)
    assert "dependency_graph" not in names
    assert "validate" in names
    assert "deliver" in names


def test_dead_code_requires_cross_checks_and_git_mutation_is_blocked():
    plan = build_repository_intelligence_plan("Health audit", mode="health")
    policy = plan["execution_policy"]
    assert policy["do_not_claim_dead_code_from_single_search"] is True
    assert policy["no_destructive_git_actions"] is True
    assert policy["no_automatic_issue_or_pr_mutation"] is True
    assert "dead_code_findings_require_cross_checks" in plan["quality_gates"]


def test_regression_risk_model_prioritizes_security_and_state_changes():
    plan = build_repository_intelligence_plan("Release readiness", mode="release")
    risk = next(stage for stage in plan["stages"] if stage["name"] == "regression_risk")
    scoring = risk["scoring"]
    assert scoring["security_or_authorization_change"] >= scoring["central_shared_component"]
    assert scoring["state_or_schema_change"] >= scoring["workflow_or_packaging_change"]
    assert sum(scoring.values()) == 100
