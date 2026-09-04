from __future__ import annotations

from plugins.universal_creator import build_universal_execution_plan


def test_universal_creator_combines_code_documents_and_images():
    plan = build_universal_execution_plan(
        "Build an application, create a PDF manual, and generate product artwork",
        artifacts=["software", "pdf", "picture"],
    )

    assert plan["ok"] is True
    assert plan["artifact_types"] == ["code", "document", "image"]
    assert "software" in plan["specialists"]
    assert "documents" in plan["specialists"]
    assert "media" in plan["specialists"]
    assert "testing" in plan["required_capabilities"]
    assert "document_generation" in plan["required_capabilities"]
    assert "image_generation" in plan["required_capabilities"]
    assert plan["execution_policy"]["require_evidence_before_completion"] is True


def test_universal_creator_defaults_to_broad_creation_stack():
    plan = build_universal_execution_plan("Create the complete project")

    assert plan["artifact_types"] == ["code", "document", "image", "research"]
    assert "discover_tools" in plan["preferred_tool_hints"]
    assert any(phase["name"] == "repair" for phase in plan["phases"])


def test_universal_creator_keeps_external_actions_gated_by_default():
    plan = build_universal_execution_plan(
        "Prepare and publish a release",
        artifacts=["code", "automation"],
    )

    assert plan["external_actions_allowed"] is False
    assert plan["execution_policy"]["external_side_effects_require_policy_approval"] is True


def test_universal_creator_aliases_common_output_names():
    plan = build_universal_execution_plan(
        "Create business outputs",
        artifacts=["docx", "xlsx", "photo", "video", "workflow"],
    )

    assert plan["artifact_types"] == ["document", "data", "image", "media", "automation"]
