from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "artifact_preview_experience_v6.py"
spec = spec_from_file_location("artifact_preview_experience_v6", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_default_preview_types_cover_major_artifacts():
    plan = module.build_artifact_preview_plan("show outputs")
    assert plan["artifact_types"] == ["document", "spreadsheet", "presentation", "image", "media", "code"]
    assert "validation_evidence_attached" in plan["quality_gates"]


def test_aliases_normalize_and_deduplicate():
    plan = module.build_artifact_preview_plan("review", artifact_types=["word", "pdf", "excel", "powerpoint", "photo", "video", "source"])
    assert plan["artifact_types"] == ["document", "spreadsheet", "presentation", "image", "media", "code"]


def test_active_content_is_never_executed_even_if_flag_is_true():
    plan = module.build_artifact_preview_plan("preview", allow_active_content=True)
    policy = plan["execution_policy"]
    assert policy["active_content_allowed"] is True
    assert policy["execute_embedded_code_or_macros"] is False
    assert policy["follow_remote_embedded_references"] is False


def test_preview_does_not_mutate_source_or_imply_edit_support():
    policy = module.build_artifact_preview_plan("preview")["execution_policy"]
    assert policy["mutate_source_during_preview"] is False
    assert policy["do_not_claim_edit_support_from_preview_support"] is True


def test_preview_item_limit_is_bounded():
    assert module.build_artifact_preview_plan("x", max_items=0)["limits"]["max_items"] == 1
    assert module.build_artifact_preview_plan("x", max_items=999)["limits"]["max_items"] == 100


def test_compare_adds_comparison_without_source_mutation():
    plan = module.build_artifact_preview_plan("compare", mode="compare")
    ids = [stage["id"] for stage in plan["stages"]]
    assert "comparison" in ids
    assert plan["execution_policy"]["mutate_source_during_preview"] is False


def test_gallery_adds_grouping_stage():
    plan = module.build_artifact_preview_plan("gallery", mode="gallery")
    assert "grouping" in [stage["id"] for stage in plan["stages"]]


def test_unknown_mode_and_type_fall_back_safely():
    plan = module.build_artifact_preview_plan("x", artifact_types=["unknown"], mode="nope")
    assert plan["mode"] == "preview"
    assert plan["artifact_types"] == ["document"]


def test_visual_fidelity_requires_separate_evidence():
    policy = module.build_artifact_preview_plan("office preview")["execution_policy"]
    assert policy["do_not_claim_visual_fidelity_without_render_evidence"] is True
    assert policy["validation_required_before_preview_ready_claim"] is True


def test_blocked_artifacts_must_remain_visible():
    policy = module.build_artifact_preview_plan("review outputs")["execution_policy"]
    assert policy["blocked_or_unsupported_items_must_be_visible"] is True
