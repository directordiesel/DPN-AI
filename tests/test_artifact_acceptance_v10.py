from pathlib import Path

from app.artifact_acceptance_v10 import inspect_artifact_acceptance
from app.artifact_studio import ArtifactStudio


def test_document_acceptance_requires_requested_title_and_headings(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_document(
        "operations",
        "Operations Review",
        [
            {"heading": "Executive Summary", "body": "Current operating position."},
            {"heading": "Risks", "body": "No critical blockers."},
        ],
    )
    assert result["professional_ready"] is True
    assert result["acceptance"]["accepted"] is True
    assert result["acceptance"]["missing_items"] == []


def test_pdf_acceptance_requires_requested_title_and_headings(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_pdf(
        "briefing",
        "Executive Briefing",
        [{"heading": "Decision", "body": "Proceed with the governed checkpoint."}],
    )
    assert result["professional_ready"] is True
    assert result["acceptance"]["accepted"] is True


def test_spreadsheet_acceptance_requires_sheet_names_and_headers(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_spreadsheet(
        "pipeline",
        "Pipeline",
        [{"name": "Summary", "rows": [["Stage", "Value"], ["Qualified", 125000]]}],
    )
    assert result["professional_ready"] is True
    assert result["acceptance"]["accepted"] is True
    assert set(result["acceptance"]["required_items"]) == {"Summary", "Stage", "Value"}


def test_presentation_acceptance_requires_deck_and_slide_titles(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_presentation(
        "strategy",
        "Strategy Review",
        [
            {"title": "Priorities", "bullets": ["Reliability", "Security"]},
            {"title": "Next Steps", "bullets": ["Validate", "Release"]},
        ],
    )
    assert result["professional_ready"] is True
    assert result["acceptance"]["accepted"] is True


def test_acceptance_fails_closed_when_required_content_is_missing(tmp_path: Path):
    studio = ArtifactStudio(tmp_path)
    generated = studio.create_document(
        "report",
        "Quarterly Report",
        [{"heading": "Summary", "body": "Evidence-backed summary."}],
    )
    target = tmp_path / generated["path"]

    result = inspect_artifact_acceptance(
        target,
        tmp_path,
        required_items=["Quarterly Report", "Summary", "Missing Required Section"],
    )

    assert result.accepted is False
    assert result.missing_items == ("Missing Required Section",)


def test_acceptance_blocks_workspace_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.docx"
    outside.write_bytes(b"not-a-document")
    try:
        inspect_artifact_acceptance(outside, tmp_path, required_items=["Required"])
    except ValueError:
        pass
    else:
        raise AssertionError("workspace escape must fail closed")
