from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "multimodal_vision_v7.py"
spec = spec_from_file_location("multimodal_vision_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_defaults_are_bounded_and_evidence_gated():
    plan = module.build_multimodal_vision_plan("inspect image")
    assert plan["input_kinds"] == ["image"]
    assert plan["limits"]["max_visual_inputs"] == 24
    assert plan["execution_policy"]["require_real_visual_input_for_visual_claims"] is True
    assert plan["execution_policy"]["never_silently_fallback_to_text_only_for_visual_tasks"] is True


def test_aliases_normalize_without_duplicates():
    plan = module.build_multimodal_vision_plan(
        "inspect",
        input_kinds=["photo", "picture", "screen", "pdf", "pdf_page", "graph", "clip", "frame"],
    )
    assert plan["input_kinds"] == [
        "image",
        "screenshot",
        "document",
        "document_page",
        "chart",
        "video",
        "video_frame",
    ]


def test_document_path_prefers_native_extraction_before_ocr():
    plan = module.build_multimodal_vision_plan("read", task="document", input_kinds=["document"])
    ids = [stage["id"] for stage in plan["stages"]]
    assert "document_context" in ids
    assert plan["execution_policy"]["native_extraction_before_ocr"] is True
    assert plan["execution_policy"]["ocr_is_fallback_not_default"] is True


def test_video_path_is_temporally_bounded():
    plan = module.build_multimodal_vision_plan("analyze clip", task="video", input_kinds=["video"])
    ids = [stage["id"] for stage in plan["stages"]]
    assert "temporal_context" in ids
    assert plan["execution_policy"]["do_not_claim_unseen_video_intervals"] is True
    assert plan["limits"]["max_video_frames"] == 32


def test_compare_requires_alignment_without_unmeasured_pixel_claims():
    plan = module.build_multimodal_vision_plan("compare", task="compare", input_kinds=["image"])
    assert "alignment" in [stage["id"] for stage in plan["stages"]]
    assert plan["execution_policy"]["do_not_claim_pixel_perfect_match_without_measurement"] is True


def test_generated_images_require_post_generation_visual_review():
    plan = module.build_multimodal_vision_plan(
        "review generated image",
        task="image_generation_review",
        input_kinds=["image"],
        allow_generation=True,
    )
    ids = [stage["id"] for stage in plan["stages"]]
    assert "generation_review" in ids
    assert plan["execution_policy"]["generation_allowed"] is True
    assert plan["execution_policy"]["generated_images_require_post_generation_vision_review"] is True


def test_limits_clamp_safely():
    low = module.build_multimodal_vision_plan("x", max_visual_inputs=0, max_video_frames=0, max_iterations=-3)
    high = module.build_multimodal_vision_plan("x", max_visual_inputs=999, max_video_frames=999, max_iterations=999)
    assert low["limits"] == {"max_visual_inputs": 1, "max_video_frames": 1, "max_iterations": 0}
    assert high["limits"] == {"max_visual_inputs": 64, "max_video_frames": 96, "max_iterations": 6}


def test_completion_fails_without_actual_model_or_provider():
    result = module.evaluate_multimodal_evidence(
        inputs_present=True,
        decoded=True,
        actual_model=None,
        actual_provider="local",
        provenance_preserved=True,
        observations_recorded=True,
        cross_checked=True,
        uncertainty_reported=True,
    )
    assert result["ok"] is False
    assert "actual_model_and_provider_recorded" in result["failed_gates"]


def test_completion_fails_if_generated_visual_was_not_inspected():
    result = module.evaluate_multimodal_evidence(
        inputs_present=True,
        decoded=True,
        actual_model="vision-model",
        actual_provider="local",
        provenance_preserved=True,
        observations_recorded=True,
        cross_checked=True,
        uncertainty_reported=True,
        generated_visual_inspected=False,
    )
    assert result["status"] == "fail"
    assert "generated_visuals_inspected_before_completion" in result["failed_gates"]


def test_completion_passes_only_with_all_evidence():
    result = module.evaluate_multimodal_evidence(
        inputs_present=True,
        decoded=True,
        actual_model="vision-model",
        actual_provider="local",
        provenance_preserved=True,
        observations_recorded=True,
        cross_checked=True,
        uncertainty_reported=True,
        generated_visual_inspected=True,
    )
    assert result["ok"] is True
    assert result["failed_gates"] == []
