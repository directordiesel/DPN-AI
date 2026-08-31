import asyncio
from pathlib import Path

from app.tools.images import ComfyUIImageGenerator


def test_image_generator_explains_missing_workflow(tmp_path: Path) -> None:
    generator = ComfyUIImageGenerator("http://127.0.0.1:8188", tmp_path / "missing.json", tmp_path / "workspace")
    result = asyncio.run(generator.generate("DPN AI logo"))
    assert result["ok"] is False
    assert "Export Workflow (API)" in result["error"]