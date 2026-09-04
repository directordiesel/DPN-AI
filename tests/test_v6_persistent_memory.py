from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "persistent_memory_v6.py"
spec = importlib.util.spec_from_file_location("persistent_memory_v6", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_plan_enforces_provenance_and_contradiction_policy():
    plan = module.build_persistent_memory_plan("Continue a large software project")
    assert plan["features"]["contradiction_tracking"] is True
    assert plan["execution_policy"]["do_not_treat_memory_as_ground_truth"] is True
    assert plan["execution_policy"]["do_not_overwrite_conflicting_memory_silently"] is True
    assert "source_provenance_recorded" in plan["quality_gates"]


def test_project_scope_and_repository_artifact_history_enabled():
    plan = module.build_persistent_memory_plan("Resume project", project_id="dpn-ai")
    assert plan["project_id"] == "dpn-ai"
    assert plan["features"]["repository_graph"] is True
    assert plan["features"]["artifact_history"] is True


def test_recall_is_bounded():
    assert module.build_persistent_memory_plan("x", max_recall_items=999)["stages"][1]["max_items"] == 200
    assert module.build_persistent_memory_plan("x", max_recall_items=1)["stages"][1]["max_items"] == 5


def test_invalid_memory_classes_fall_back_safely():
    plan = module.build_persistent_memory_plan("x", memory_classes=["nonsense"])
    assert plan["memory_classes"] == ["fact"]


def test_invalid_retention_falls_back_to_project():
    plan = module.build_persistent_memory_plan("x", retention="forever-and-ever")
    assert plan["retention"] == "project"


def test_primary_corroborated_memory_can_be_durable_candidate():
    result = module.score_memory_candidate(confidence=0.95, source_tier="primary", corroborating_sources=3)
    assert result["disposition"] == "durable_candidate"
    assert result["score"] >= 0.82


def test_contradiction_is_quarantined_even_with_high_confidence():
    result = module.score_memory_candidate(confidence=1.0, source_tier="primary", corroborating_sources=5, contradicted=True)
    assert result["disposition"] == "quarantine"
    assert result["requires_review"] is True


def test_stale_memory_is_penalized():
    fresh = module.score_memory_candidate(confidence=0.8, source_tier="verified", stale=False)
    stale = module.score_memory_candidate(confidence=0.8, source_tier="verified", stale=True)
    assert stale["score"] < fresh["score"]


def test_secret_storage_is_explicitly_forbidden():
    plan = module.build_persistent_memory_plan("Remember project details")
    assert plan["execution_policy"]["never_store_secrets_in_plaintext_memory"] is True


def test_forgetting_requires_scope_and_reason_when_enabled():
    plan = module.build_persistent_memory_plan("Maintain memory", allow_forgetting=True)
    assert plan["execution_policy"]["forgetting_requires_explicit_scope_and_reason"] is True
