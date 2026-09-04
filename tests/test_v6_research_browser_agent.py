from __future__ import annotations

from plugins.research_browser_agent import build_research_browser_plan


def test_standard_research_plan_requires_freshness_and_citations():
    plan = build_research_browser_plan("Find the latest official requirements")
    assert plan["mode"] == "research"
    assert plan["depth"] == "standard"
    assert plan["require_current_information"] is True
    assert plan["require_citations"] is True
    assert "freshness_verified" in plan["quality_gates"]
    assert "material_claims_cited" in plan["quality_gates"]
    assert plan["execution_policy"]["never_invent_sources_or_citations"] is True


def test_deep_research_caps_sources_at_thirty():
    plan = build_research_browser_plan("Deep research", depth="deep", max_sources=200)
    assert plan["max_sources"] == 30
    assert plan["target_sources"] == 30


def test_quick_research_uses_smaller_target():
    plan = build_research_browser_plan("Quick answer", depth="quick", max_sources=20)
    assert plan["target_sources"] == 5


def test_compare_and_verify_add_cross_check_stage():
    for mode in ("compare", "verify"):
        plan = build_research_browser_plan("Check conflicting claims", mode=mode)
        names = [stage["name"] for stage in plan["stages"]]
        assert "cross_check" in names


def test_browse_mode_keeps_actions_off_by_default():
    plan = build_research_browser_plan("Inspect an interactive page", mode="browse")
    stage = next(stage for stage in plan["stages"] if stage["name"] == "browser_workflow")
    assert stage["browser_actions_allowed"] is False
    assert plan["execution_policy"]["browser_private_network_protections_must_remain_enabled"] is True
    assert plan["execution_policy"]["browser_downloads_remain_disabled"] is True


def test_monitor_mode_does_not_claim_scheduler_activation():
    plan = build_research_browser_plan("Watch a source for changes", mode="monitor")
    names = [stage["name"] for stage in plan["stages"]]
    assert "change_baseline" in names
    assert plan["execution_policy"]["do_not_claim_future_monitoring_is_active_without_scheduler_evidence"] is True


def test_document_package_requests_artifact_creation():
    plan = build_research_browser_plan("Produce an executive research package", output="document_package")
    assert "artifact_creation" in plan["required_capabilities"]


def test_invalid_options_fall_back_safely():
    plan = build_research_browser_plan("Research", mode="unknown", depth="extreme", output="mystery")
    assert plan["mode"] == "research"
    assert plan["depth"] == "standard"
    assert plan["output"] == "report"


def test_source_floor_is_one():
    plan = build_research_browser_plan("Research", max_sources=0)
    assert plan["max_sources"] == 1
    assert plan["target_sources"] == 1
