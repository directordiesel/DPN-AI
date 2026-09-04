from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "project_intelligence_v7.py"
spec = spec_from_file_location("project_intelligence_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_project_identity_and_current_state_are_required():
    plan = module.build_project_intelligence_plan("continue build", "dpn-ai")
    assert plan["ok"] is True
    assert plan["execution_policy"]["require_fresh_repository_state"] is True
    assert "current_repository_state_refreshed" in plan["quality_gates"]


def test_domains_are_bounded_and_deduplicated():
    plan = module.build_project_intelligence_plan("x", "p", ["repository", "repository", "security", "bad"])
    assert plan["domains"] == ["repository", "security"]
    assert module.build_project_intelligence_plan("x", "p", max_recall_items=999)["limits"]["max_recall_items"] == 250


def test_memory_is_not_ground_truth_and_conflicts_are_preserved():
    policy = module.build_project_intelligence_plan("x", "p")["execution_policy"]
    assert policy["memory_is_context_not_ground_truth"] is True
    assert policy["never_silently_overwrite_conflicts"] is True
    assert policy["never_promote_inference_to_verified_fact"] is True


def test_project_lineage_tracks_tests_artifacts_and_releases():
    policy = module.build_project_intelligence_plan("x", "p")["execution_policy"]
    assert policy["track_file_symbol_component_lineage"] is True
    assert policy["track_test_and_failure_history"] is True
    assert policy["track_artifact_and_release_lineage"] is True


def test_missing_evidence_blocks_completion():
    result = module.evaluate_project_intelligence_evidence({"project_identity": "p"})
    assert result["ok"] is False
    assert "verification" in result["missing_evidence"]
    assert result["completion_allowed"] is False


def test_verified_evidence_allows_completion_but_discloses_contradictions():
    evidence = {
        "project_identity": "p", "scope": "repo", "provenance": ["commit"], "confidence": 0.9,
        "current_state": {"head": "abc"}, "reconciliation": {"done": True}, "verification": ["tests"],
        "unresolved_contradictions": ["old architecture note"]
    }
    result = module.evaluate_project_intelligence_evidence(evidence)
    assert result["ok"] is True
    assert result["policy"]["contradictions_must_be_disclosed"] is True


def test_blockers_cannot_be_reported_as_success():
    evidence = {
        "project_identity": "p", "scope": "repo", "provenance": ["commit"], "confidence": 1,
        "current_state": {"head": "abc"}, "reconciliation": {"done": True}, "verification": ["tests"],
        "blockers": ["CI failed"]
    }
    result = module.evaluate_project_intelligence_evidence(evidence)
    assert result["ok"] is False
    assert result["completion_allowed"] is False


def test_plaintext_secret_storage_is_forbidden():
    assert module.build_project_intelligence_plan("x", "p")["execution_policy"]["never_store_secrets_in_plaintext"] is True
