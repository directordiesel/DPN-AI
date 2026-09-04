from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "native_vision_reasoning_v6.py"
spec = spec_from_file_location("native_vision_reasoning_v6", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_defaults_require_real_vision_capability():
    plan = module.build_native_vision_reasoning_plan("inspect image")
    assert plan["input_kinds"] == ["image"]
    assert plan["execution_policy"]["vision_model_required"] is True
    assert plan["execution_policy"]["do_not_silently_use_text_only_model_for_visual_claims"] is True


def test_input_aliases_normalize_and_deduplicate():
    plan = module.build_native_vision_reasoning_plan("inspect", input_kinds=["photo", "picture", "pdf_page", "screen", "frame", "graph"])
    assert plan["input_kinds"] == ["image", "document_page", "screenshot", "video_frame", "chart"]


def test_document_mode_prefers_native_text_before_ocr():
    plan = module.build_native_vision_reasoning_plan("read page", mode="document", input_kinds=["document_page"])
    ids = [stage["id"] for stage in plan["stages"]]
    assert "page_context" in ids
    assert plan["execution_policy"]["native_text_extraction_before_ocr"] is True
    assert plan["execution_policy"]["ocr_is_fallback_not_default"] is True


def test_video_mode_preserves_timestamps_and_unseen_interval_safety():
    plan = module.build_native_vision_reasoning_plan("analyze clip", mode="video", input_kinds=["video_frame"])
    assert "temporal_context" in [stage["id"] for stage in plan["stages"]]
    assert plan["execution_policy"]["do_not_claim_unseen_video_intervals"] is True
    assert plan["execution_policy"]["preserve_page_frame_timestamp_provenance"] is True


def test_compare_mode_adds_alignment_and_no_pixel_claim_without_measurement():
    plan = module.build_native_vision_reasoning_plan("compare", mode="compare", input_kinds=["image"])
    assert "alignment" in [stage["id"] for stage in plan["stages"]]
    assert plan["execution_policy"]["do_not_claim_pixel_perfect_match_without_measurement"] is True


def test_limits_are_bounded():
    low = module.build_native_vision_reasoning_plan("x", max_inputs=0, max_iterations=-5)
    high = module.build_native_vision_reasoning_plan("x", max_inputs=999, max_iterations=999)
    assert low["limits"] == {"max_inputs": 1, "max_iterations": 0}
    assert high["limits"] == {"max_inputs": 50, "max_iterations": 5}


def test_actual_model_and_provider_are_required_evidence():
    plan = module.build_native_vision_reasoning_plan("inspect")
    assert "actual_model_recorded" in plan["quality_gates"]
    assert plan["execution_policy"]["record_actual_model_and_provider"] is True


def test_missing_visual_input_cannot_be_replaced_by_description():
    policy = module.build_native_vision_reasoning_plan("inspect")["execution_policy"]
    assert policy["do_not_reason_from_missing_visual_input"] is True


def test_invalid_mode_and_kind_fall_back_safely():
    plan = module.build_native_vision_reasoning_plan("x", mode="bad", input_kinds=["unknown"])
    assert plan["mode"] == "inspect"
    assert plan["input_kinds"] == ["image"]


def test_external_vision_provider_still_uses_existing_policy_gate():
    policy = module.build_native_vision_reasoning_plan("inspect")["execution_policy"]
    assert policy["external_model_use_requires_existing_policy_permission"] is True
