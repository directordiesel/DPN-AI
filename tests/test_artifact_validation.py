from pathlib import Path

from app.artifact_validation import validate_artifact


def test_validate_artifact_hashes_supported_file(tmp_path: Path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"pdf-data")
    result = validate_artifact(target, tmp_path)
    assert result.valid is True
    assert result.artifact_type == "pdf"
    assert result.size_bytes == 8
    assert len(result.sha256) == 64
    assert result.warnings == ()


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
