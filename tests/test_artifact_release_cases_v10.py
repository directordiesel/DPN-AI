from pathlib import Path

from app.artifact_studio import ArtifactStudio


def _assert_release_ready(result: dict):
    assert result["ok"] is True
    assert result["profile"]["ready"] is True
    assert result["validation"]["valid"] is True
    assert result["quality"]["professional_ready"] is True
    assert result["quality"]["score"] == 1.0
    assert result["acceptance"]["accepted"] is True
    assert result["professional_ready"] is True


def test_release_docx_professional_end_to_end(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_document(
        "release-docx",
        "Operations Review",
        [
            {"heading": "Executive Summary", "body": "Operational performance remains within approved targets."},
            {"heading": "Actions", "body": ["Verify controls", "Publish reviewed evidence"]},
        ],
    )
    _assert_release_ready(result)


def test_release_pdf_professional_end_to_end(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_pdf(
        "release-pdf",
        "Security Review",
        [
            {"heading": "Scope", "body": "This report covers the approved v10 artifact boundary."},
            {"heading": "Conclusion", "body": "No unsupported completion claim is permitted."},
        ],
    )
    _assert_release_ready(result)


def test_release_xlsx_professional_end_to_end(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_spreadsheet(
        "release-xlsx",
        "Performance Workbook",
        [
            {
                "name": "Summary",
                "rows": [["Metric", "Actual", "Target"], ["Quality", 100, 100], ["Reliability", 100, 100]],
                "formulas": {"B4": "AVERAGE(B2:B3)"},
                "charts": [{"type": "bar", "title": "Actual vs Target", "min_col": 2, "max_col": 3, "min_row": 1, "max_row": 3, "category_col": 1, "anchor": "E2"}],
            }
        ],
    )
    _assert_release_ready(result)


def test_release_pptx_professional_end_to_end(tmp_path: Path):
    result = ArtifactStudio(tmp_path).create_presentation(
        "release-pptx",
        "Executive Program Review",
        [
            {"title": "Status", "bullets": ["Validated implementation", "Fail-closed release gates"]},
            {"title": "Next Actions", "bullets": ["Complete benchmark evidence", "Verify exact-head CI"]},
        ],
    )
    _assert_release_ready(result)
