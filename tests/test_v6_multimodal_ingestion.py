from __future__ import annotations

import importlib.util
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "multimodal_ingestion_v6.py"
spec = importlib.util.spec_from_file_location("multimodal_ingestion_v6", PLUGIN)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_classifies_mixed_inputs_and_routes_specialists():
    plan = module.build_multimodal_ingestion_plan(
        "Understand this mixed project",
        ["report.pdf", "sales.xlsx", "photo.png", "demo.mp4", "server.log", "src/main.py", "bundle.zip"],
    )
    assert set(plan["input_kinds"]) >= {"document", "spreadsheet", "image", "video", "log", "code", "archive"}
    assert "coding-agent-v6" in plan["specialist_routes"]
    assert "image-vision-studio-v6" in plan["specialist_routes"]
    assert "repository-intelligence-v6" in plan["specialist_routes"]


def test_unknown_types_are_disclosed_not_invented():
    plan = module.build_multimodal_ingestion_plan("Inspect", ["mystery.xyz"])
    assert plan["unsupported_inputs"] == ["mystery.xyz"]
    assert plan["inputs"][0]["supported"] is False
    assert plan["inputs"][0]["route"] == "universal-creator-v6"


def test_file_and_frame_limits_are_bounded():
    plan = module.build_multimodal_ingestion_plan("Inspect", ["a.txt"], max_files=9999, max_media_frames=99)
    assert plan["stages"][0]["max_files"] == 500
    assert plan["media_policy"]["max_frames_per_video"] == 12


def test_security_and_evidence_policy_is_explicit():
    policy = module.build_multimodal_ingestion_plan("Inspect", ["code.py", "archive.zip"])["execution_policy"]
    assert policy["do_not_execute_ingested_code"] is True
    assert policy["archives_must_be_inspected_before_extraction"] is True
    assert policy["do_not_claim_unread_content"] is True
    assert policy["original_inputs_are_read_only_by_default"] is True


def test_windows_paths_classify_consistently():
    item = module.classify_input(r"folder\image.JPEG")
    assert item["kind"] == "image"
    assert item["extension"] == ".jpeg"


def test_provenance_gate_is_enabled_by_default():
    plan = module.build_multimodal_ingestion_plan("Correlate files", ["a.pdf", "b.csv"])
    assert plan["execution_policy"]["preserve_provenance"] is True
    assert "provenance_preserved" in plan["quality_gates"]
    assert any(stage["name"] == "correlate" for stage in plan["stages"])
