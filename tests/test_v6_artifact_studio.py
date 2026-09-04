from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "artifact_studio.py"
spec = importlib.util.spec_from_file_location("artifact_studio", MODULE_PATH)
artifact_studio = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(artifact_studio)


def test_artifact_plan_defaults_to_docx_and_validation():
    plan = artifact_studio.build_artifact_mission("Create an executive report")
    assert plan["ok"] is True
    assert plan["mode"] == "create"
    assert plan["formats"] == ["docx"]
    assert "create_word_document" in plan["preferred_tools"]
    assert plan["policy"]["validate_before_completion_claim"] is True


def test_artifact_plan_handles_aliases_and_edit_mode():
    plan = artifact_studio.build_artifact_mission(
        "Revise the package",
        formats=["word", "excel", "powerpoint", "pdf"],
        existing_artifacts=["generated/source.docx"],
    )
    assert plan["mode"] == "edit"
    assert plan["formats"] == ["docx", "xlsx", "pptx", "pdf"]
    assert plan["policy"]["snapshot_before_overwriting_existing"] is True
    assert plan["policy"]["cross_format_consistency_required"] is True


def _write_ooxml(path: Path, required: set[str]):
    with zipfile.ZipFile(path, "w") as archive:
        for member in required:
            archive.writestr(member, "<xml />")


def test_validates_minimal_docx_package(tmp_path):
    target = tmp_path / "sample.docx"
    _write_ooxml(target, {"[Content_Types].xml", "word/document.xml"})
    result = artifact_studio.validate_artifact(tmp_path, "sample.docx", "docx")
    assert result["ok"] is True
    assert result["format"] == "docx"


def test_rejects_corrupt_office_package(tmp_path):
    target = tmp_path / "sample.xlsx"
    target.write_bytes(b"not a zip file")
    result = artifact_studio.validate_artifact(tmp_path, "sample.xlsx", "xlsx")
    assert result["ok"] is False
    assert any("valid Office Open XML" in error for error in result["errors"])


def test_validates_pdf_signature_and_eof(tmp_path):
    target = tmp_path / "sample.pdf"
    target.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    result = artifact_studio.validate_artifact(tmp_path, "sample.pdf", "pdf")
    assert result["ok"] is True


def test_rejects_workspace_escape(tmp_path):
    result = artifact_studio.validate_artifact(tmp_path, "../outside.docx", "docx")
    assert result["ok"] is False
    assert any("escapes the workspace" in error for error in result["errors"])
