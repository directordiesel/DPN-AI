from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "browser_research_v7.py"
spec = spec_from_file_location("browser_research_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_plan_is_bounded_and_safe_by_default():
    plan = module.build_browser_research_v7_plan("research current release")
    assert plan["ok"] is True
    assert plan["execution_policy"]["browser_actions_allowed"] is False
    assert plan["execution_policy"]["downloads_allowed"] is False
    assert plan["execution_policy"]["browser_private_network_protections_must_remain_enabled"] is True
    assert plan["execution_policy"]["external_side_effects_require_approval"] is True


def test_invalid_values_fall_back_and_limits_clamp():
    plan = module.build_browser_research_v7_plan(
        "x", mode="bad", depth="bad", output="bad", max_sources=999, max_pages_per_source=999
    )
    assert plan["mode"] == "research"
    assert plan["depth"] == "standard"
    assert plan["output"] == "report"
    assert plan["limits"]["max_sources"] == 40
    assert plan["limits"]["max_pages_per_source"] == 20


def test_compare_mode_requires_cross_check():
    plan = module.build_browser_research_v7_plan("compare", mode="compare")
    assert "cross_check" in [stage["id"] for stage in plan["stages"]]


def test_browse_mode_records_browser_workflow():
    plan = module.build_browser_research_v7_plan("browse", mode="browse", allow_browser_actions=True)
    assert "browser_workflow" in [stage["id"] for stage in plan["stages"]]
    assert plan["execution_policy"]["browser_actions_allowed"] is True


def test_monitor_mode_does_not_fake_scheduling():
    plan = module.build_browser_research_v7_plan("watch", mode="monitor")
    assert "baseline" in [stage["id"] for stage in plan["stages"]]
    assert plan["execution_policy"]["do_not_claim_future_monitoring_without_scheduler_evidence"] is True


def test_current_information_requires_freshness_gate():
    plan = module.build_browser_research_v7_plan("latest", require_current_information=True)
    assert "freshness_verified" in plan["quality_gates"]
    assert plan["execution_policy"]["record_publication_event_and_retrieval_dates_separately"] is True


def test_evaluator_accepts_complete_evidence():
    result = module.evaluate_research_evidence_v7({
        "sources": [{"id": "s1", "url": "https://example.test/source", "title": "Source", "retrieved_at": "2026-09-04T10:00:00Z"}],
        "claims": [{"id": "c1", "claim": "fact", "source_ids": ["s1"], "material": True}],
        "contradictions": [],
        "freshness_checked": True,
        "citation_audited": True,
    })
    assert result["ok"] is True
    assert result["completion_allowed"] is True


def test_evaluator_rejects_unsupported_material_claims():
    result = module.evaluate_research_evidence_v7({
        "sources": [{"id": "s1", "url": "https://example.test/source", "title": "Source", "retrieved_at": "2026-09-04T10:00:00Z"}],
        "claims": [{"id": "c1", "claim": "fact", "source_ids": ["missing"], "material": True}],
        "contradictions": [],
        "freshness_checked": True,
        "citation_audited": True,
    })
    assert result["ok"] is False
    assert "material_claims_without_valid_source_links" in result["failures"]


def test_evaluator_rejects_missing_freshness_and_citation_audit():
    result = module.evaluate_research_evidence_v7({
        "sources": [{"id": "s1", "url": "https://example.test/source", "title": "Source", "retrieved_at": "2026-09-04T10:00:00Z"}],
        "claims": [],
        "contradictions": [],
    })
    assert "freshness_not_verified" in result["failures"]
    assert "citations_not_audited" in result["failures"]


def test_evaluator_requires_contradiction_review_even_if_none_found():
    result = module.evaluate_research_evidence_v7({
        "sources": [{"id": "s1", "url": "https://example.test/source", "title": "Source", "retrieved_at": "2026-09-04T10:00:00Z"}],
        "claims": [],
        "freshness_checked": True,
        "citation_audited": True,
    })
    assert "contradiction_review_missing" in result["failures"]


def test_fabricated_source_is_hard_failure():
    result = module.evaluate_research_evidence_v7({
        "sources": [{"id": "s1", "url": "https://example.test/source", "title": "Source", "retrieved_at": "2026-09-04T10:00:00Z"}],
        "claims": [],
        "contradictions": [],
        "freshness_checked": True,
        "citation_audited": True,
        "fabricated_source_detected": True,
    })
    assert "fabricated_source_detected" in result["failures"]
