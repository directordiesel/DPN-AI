from pathlib import Path

import pytest

from app.artifact_profiles_v10 import (
    DEFAULT_PROFILE_BY_TYPE,
    PROFESSIONAL_ARTIFACT_PROFILES,
    evaluate_artifact_profile_request,
    get_artifact_profile,
)
from app.artifact_studio import ArtifactStudio


def test_all_four_professional_formats_have_default_governed_profiles():
    assert set(DEFAULT_PROFILE_BY_TYPE) == {"docx", "pdf", "xlsx", "pptx"}
    assert set(DEFAULT_PROFILE_BY_TYPE.values()) == set(PROFESSIONAL_ARTIFACT_PROFILES)


def test_profile_type_mismatch_fails_closed():
    with pytest.raises(ValueError):
        get_artifact_profile("executive_deck_pptx", "docx")


def test_report_profile_rejects_empty_section_before_file_write(tmp_path: Path):
    studio = ArtifactStudio(tmp_path)
    result = studio.create_document(
        "empty-report",
        "Empty Report",
        [{"heading": "Summary", "body": ""}],
    )
    assert result["ok"] is False
    assert result["professional_ready"] is False
    assert result["profile"]["ready"] is False
    assert "one or more report sections are empty" in result["profile"]["failures"]
    assert not (tmp_path / "generated" / "empty-report.docx").exists()


def test_workbook_profile_rejects_duplicate_sheet_names():
    result = evaluate_artifact_profile_request(
        profile_id=None,
        artifact_type="xlsx",
        title="Analysis",
        items=[
            {"name": "Summary", "rows": [["Metric", "Value"], ["A", 1]]},
            {"name": "summary", "rows": [["Metric", "Value"], ["B", 2]]},
        ],
    )
    assert result.ready is False
    assert result.metrics["duplicate_sheet_names"] == 1


def test_executive_deck_profile_rejects_overfull_slide_before_file_write(tmp_path: Path):
    studio = ArtifactStudio(tmp_path)
    result = studio.create_presentation(
        "deck",
        "Executive Deck",
        [{"title": "Priorities", "bullets": [f"Item {index}" for index in range(9)]}],
    )
    assert result["ok"] is False
    assert result["profile"]["ready"] is False
    assert "one or more presentation slides exceed eight bullets" in result["profile"]["failures"]
    assert not (tmp_path / "generated" / "deck.pptx").exists()


def test_profile_evidence_is_included_in_successful_professional_output(tmp_path: Path):
    studio = ArtifactStudio(tmp_path)
    result = studio.create_pdf(
        "report",
        "Quarterly Review",
        [{"heading": "Summary", "body": "Performance remained within approved operating targets."}],
    )
    assert result["ok"] is True
    assert result["profile"]["profile_id"] == "formal_report_pdf"
    assert result["profile"]["ready"] is True
    assert result["validation"]["valid"] is True
    assert result["quality"]["professional_ready"] is True
    assert result["acceptance"]["accepted"] is True
    assert result["professional_ready"] is True
