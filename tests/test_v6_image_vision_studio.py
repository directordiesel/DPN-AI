from pathlib import Path
import importlib.util


def _load_plugin():
    path = Path(__file__).resolve().parents[1] / "plugins" / "image_vision_studio.py"
    spec = importlib.util.spec_from_file_location("image_vision_studio", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_generate_plan_has_validation_and_feedback_loop():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Create a DPN AI logo", mode="generate", max_iterations=3)
    assert plan["ok"] is True
    assert plan["mode"] == "generate"
    assert "artifact_exists" in plan["quality_gates"]
    assert plan["feedback_loop"]["enabled"] is True
    assert plan["feedback_loop"]["max_iterations"] == 3
    assert any(stage["name"] == "render" for stage in plan["stages"])


def test_edit_requires_reference_image():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Fix this image", mode="edit", reference_images=[])
    assert plan["input_requirement"] == "reference_image_required"


def test_analysis_mode_skips_render_stage():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Analyze image", mode="analyze", reference_images=["input.png"])
    assert plan["input_requirement"] == "ready"
    assert not any(stage["name"] == "render" for stage in plan["stages"])


def test_feedback_loop_is_bounded():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Iterate", mode="iterate", max_iterations=99)
    assert plan["feedback_loop"]["max_iterations"] == 5


def test_feedback_loop_can_be_disabled():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Generate once", require_feedback_loop=False, max_iterations=3)
    assert plan["feedback_loop"]["enabled"] is False
    assert plan["feedback_loop"]["max_iterations"] == 0


def test_invalid_mode_and_backend_fall_back_safely():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Create image", mode="weird", backend="unknown")
    assert plan["mode"] == "generate"
    assert plan["backend"] == "auto"


def test_plan_records_reproducibility_and_evidence_policy():
    module = _load_plugin()
    plan = module.build_image_vision_plan("Create image")
    policy = plan["execution_policy"]
    assert policy["record_seed_and_backend"] is True
    assert policy["do_not_claim_visual_match_without_evidence"] is True
    assert policy["backend_fallback_must_be_reported"] is True
