from pathlib import Path

from app.artifact_quality_v10 import inspect_artifact_quality
from app.artifact_studio import ArtifactStudio


def test_professional_quality_accepts_generated_docx_pdf_xlsx_pptx(tmp_path: Path):
    studio = ArtifactStudio(tmp_path)
    results = [
        studio.create_document(
            "brief",
            "Executive Brief",
            [{"heading": "Summary", "body": "Verified professional document content."}],
        ),
        studio.create_pdf(
            "brief",
            "Executive Brief",
            [{"heading": "Summary", "body": "Verified professional PDF content."}],
        ),
        studio.create_spreadsheet(
            "finance",
            "Finance",
            [{"name": "Summary", "rows": [["Month", "Revenue"], ["Jan", 10], ["Feb", 15]]}],
        ),
        studio.create_presentation(
            "brief",
            "Executive Brief",
            [{"title": "Summary", "bullets": ["Verified professional presentation content."]}],
        ),
    ]

    for result in results:
        assert result["ok"] is True
        target = tmp_path / result["path"]
        quality = inspect_artifact_quality(target, tmp_path)
        assert quality.professional_ready is True
        assert quality.score == 1.0
        assert quality.failures == ()


def test_professional_quality_fails_closed_for_wrong_or_empty_payload(tmp_path: Path):
    target = tmp_path / "broken.pdf"
    target.write_bytes(b"not-a-pdf")
    quality = inspect_artifact_quality(target, tmp_path)
    assert quality.professional_ready is False
    assert quality.score == 0.0
    assert quality.failures


def test_professional_quality_blocks_workspace_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.docx"
    outside.write_bytes(b"x")
    try:
        inspect_artifact_quality(outside, tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("workspace escape must fail closed")
