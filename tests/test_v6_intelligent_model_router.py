from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "intelligent_model_router.py"
spec = spec_from_file_location("intelligent_model_router", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_coding_routes_to_software_profile_and_review():
    plan = module.build_model_routing_plan("Fix the API", ["coding"])
    assert plan["model_profiles"] == ["software"]
    assert plan["independent_review_required"] is True
    assert plan["routing_policy"]["record_actual_model_and_provider"] is True


def test_vision_requires_vision_capability():
    plan = module.build_model_routing_plan("Analyze this image", ["image"])
    assert plan["task_types"] == ["vision"]
    assert plan["require_vision"] is True
    assert plan["routing_policy"]["do_not_silently_downgrade_vision_or_tool_requirements"] is True


def test_external_models_disabled_by_default():
    plan = module.build_model_routing_plan("Research", ["research"])
    assert plan["allow_external_models"] is False
    assert plan["routing_policy"]["prefer_local_by_default"] is True
    assert plan["routing_policy"]["external_requires_explicit_enablement"] is True


def test_manual_mode_preserves_user_choice_policy():
    plan = module.build_model_routing_plan("Use my chosen model", ["general"], intelligence_mode="manual")
    assert plan["routing_policy"]["manual_mode_preserves_user_model_choice"] is True


def test_aliases_and_deduplication():
    plan = module.build_model_routing_plan("Mixed work", ["code", "software", "github", "photo", "pdf", "spreadsheet", "web"])
    assert plan["task_types"] == ["coding", "repository", "vision", "documents", "data", "research"]
    assert plan["require_vision"] is True


def test_invalid_preferences_fall_back_safely():
    plan = module.build_model_routing_plan("Test", ["unknown"], intelligence_mode="weird", latency_preference="x", cost_preference="y")
    assert plan["task_types"] == ["general"]
    assert plan["intelligence_mode"] == "maximum"
    assert plan["latency_preference"] == "balanced"
    assert plan["cost_preference"] == "balanced"


def test_reviewer_can_be_disabled_explicitly():
    plan = module.build_model_routing_plan("Implement", ["coding"], require_independent_review=False)
    assert plan["independent_review_required"] is False
    assert all(stage["name"] != "review" for stage in plan["stages"])


def test_evidence_and_fallback_gates_present():
    plan = module.build_model_routing_plan("Review repo", ["repository"])
    assert "actual_model_recorded" in plan["quality_gates"]
    assert "fallback_history_recorded" in plan["quality_gates"]
    assert plan["routing_policy"]["fallbacks_must_be_disclosed"] is True
    assert plan["routing_policy"]["review_must_use_acceptance_criteria_and_tool_evidence"] is True
