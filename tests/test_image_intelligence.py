from pathlib import Path

import pytest

from app.image_intelligence import ImageIntelligence


def test_generate_request_does_not_require_source(tmp_path: Path):
    runtime = ImageIntelligence(tmp_path)
    result = runtime.build_request("generate", "Create a purple DPN logo", width=1024, height=1024)
    assert result["ok"] is True
    assert result["operation"] == "generate"
    assert result["provider_capability"] == "text_to_image"
    assert result["source_path"] is None


def test_edit_requires_existing_supported_source(tmp_path: Path):
    runtime = ImageIntelligence(tmp_path)
    with pytest.raises(ValueError, match="requires source_path"):
        runtime.build_request("edit", "Remove the background")

    source = tmp_path / "source.png"
    source.write_bytes(b"fake")
    result = runtime.build_request("edit", "Remove the background", source_path="source.png")
    assert result["provider_capability"] == "image_edit"
    assert result["source_path"] == "source.png"


def test_analyze_routes_to_vision(tmp_path: Path):
    source = tmp_path / "screen.webp"
    source.write_bytes(b"fake")
    runtime = ImageIntelligence(tmp_path)
    result = runtime.build_request("analyze", "Find the UI error", source_path="screen.webp")
    assert result["provider_capability"] == "vision"
    assert result["requires_source"] is True


def test_rejects_workspace_escape_and_unsupported_format(tmp_path: Path):
    runtime = ImageIntelligence(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        runtime.build_request("analyze", "Inspect it", source_path="../outside.png")

    bad = tmp_path / "bad.gif"
    bad.write_bytes(b"gif")
    with pytest.raises(ValueError, match="Unsupported image format"):
        runtime.build_request("analyze", "Inspect it", source_path="bad.gif")


def test_mask_only_allowed_for_edit(tmp_path: Path):
    source = tmp_path / "source.jpg"
    mask = tmp_path / "mask.png"
    source.write_bytes(b"source")
    mask.write_bytes(b"mask")
    runtime = ImageIntelligence(tmp_path)

    with pytest.raises(ValueError, match="only valid for edit"):
        runtime.build_request("analyze", "Inspect", source_path="source.jpg", mask_path="mask.png")

    result = runtime.build_request(
        "edit",
        "Replace masked object",
        source_path="source.jpg",
        mask_path="mask.png",
    )
    assert result["mask_path"] == "mask.png"


def test_dimensions_are_bounded(tmp_path: Path):
    runtime = ImageIntelligence(tmp_path)
    with pytest.raises(ValueError, match="between 64 and 4096"):
        runtime.build_request("generate", "Tiny", width=32)
    with pytest.raises(ValueError, match="between 64 and 4096"):
        runtime.build_request("generate", "Huge", height=8192)
