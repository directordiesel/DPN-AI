from pathlib import Path
import zipfile

from app.artifact_validation import validate_artifact


def _write_ooxml(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_validate_artifact_hashes_supported_pdf(tmp_path: Path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    result = validate_artifact(target, tmp_path)
    assert result.valid is True
    assert result.artifact_type == "pdf"
    assert result.size_bytes > 0
    assert len(result.sha256) == 64
    assert result.warnings == ()


def test_validate_artifact_rejects_malformed_pdf(tmp_path: Path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"pdf-data")
    result = validate_artifact(target, tmp_path)
    assert result.valid is False
    assert "missing PDF signature" in result.warnings
    assert "missing PDF EOF marker" in result.warnings


def test_validate_artifact_accepts_valid_docx_container(tmp_path: Path):
    target = tmp_path / "report.docx"
    _write_ooxml(
        target,
        {
            "[Content_Types].xml": b"<Types />",
            "word/document.xml": b"<w:document />",
        },
    )
    result = validate_artifact(target, tmp_path)
    assert result.valid is True
    assert result.warnings == ()


def test_validate_artifact_rejects_invalid_office_container(tmp_path: Path):
    target = tmp_path / "book.xlsx"
    target.write_bytes(b"not-a-zip")
    result = validate_artifact(target, tmp_path)
    assert result.valid is False
    assert "artifact is not a valid Office Open XML container" in result.warnings


def test_validate_artifact_rejects_missing_office_members(tmp_path: Path):
    target = tmp_path / "slides.pptx"
    _write_ooxml(target, {"[Content_Types].xml": b"<Types />"})
    result = validate_artifact(target, tmp_path)
    assert result.valid is False
    assert any("ppt/presentation.xml" in warning for warning in result.warnings)


def test_validate_artifact_rejects_missing_file(tmp_path: Path):
    result = validate_artifact(tmp_path / "missing.docx", tmp_path)
    assert result.valid is False
    assert "artifact file is missing" in result.warnings


def test_validate_artifact_rejects_unsupported_extension(tmp_path: Path):
    target = tmp_path / "payload.bin"
    target.write_bytes(b"data")
    result = validate_artifact(target, tmp_path)
    assert result.valid is False
    assert result.warnings[0].startswith("unsupported artifact extension")


def test_validate_artifact_blocks_workspace_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"x")
    try:
        validate_artifact(outside, tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("workspace escape must fail closed")
