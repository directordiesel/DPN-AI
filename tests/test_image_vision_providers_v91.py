from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.tools.image_vision_providers import ComfyUIImageEditor, ConfigurableVisionProvider, _workspace_file


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8xkAAAAASUVORK5CYII="
)


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "model": kwargs["model"],
            "provider": "compatible",
            "message": {"role": "assistant", "content": "A tiny valid image."},
        }


def test_workspace_file_rejects_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(PNG_1X1)
    with pytest.raises(ValueError, match="inside the DPN AI workspace"):
        _workspace_file(tmp_path, str(outside))


@pytest.mark.asyncio
async def test_vision_fails_closed_without_configured_model(tmp_path: Path):
    image = tmp_path / "sample.png"
    image.write_bytes(PNG_1X1)
    provider = ConfigurableVisionProvider(FakeGateway(), tmp_path, configured_model="")
    result = await provider.analyze("sample.png")
    assert result["ok"] is False
    assert result["configured"] is False
    assert "No vision model is configured" in result["error"]


@pytest.mark.asyncio
async def test_vision_uses_explicit_model_and_evidence(tmp_path: Path):
    image = tmp_path / "sample.png"
    image.write_bytes(PNG_1X1)
    gateway = FakeGateway()
    provider = ConfigurableVisionProvider(gateway, tmp_path, configured_model="compatible:vision-model")
    result = await provider.analyze("sample.png", prompt="What is visible?")
    assert result["ok"] is True
    assert result["model"] == "compatible:vision-model"
    assert result["provider"] == "compatible"
    assert result["analysis"] == "A tiny valid image."
    assert len(result["sha256"]) == 64
    message = gateway.calls[0]["messages"][0]
    assert message["images"][0].startswith("data:image/png;base64,")


def test_comfyui_edit_fails_closed_without_workflow(tmp_path: Path):
    editor = ComfyUIImageEditor("http://127.0.0.1:8188", "", tmp_path)
    assert editor.workflow_path is None


def test_prepare_workflow_binds_reference_prompt_seed_and_output():
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}, "_meta": {"title": "Positive Prompt"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}, "_meta": {"title": "Negative Prompt"}},
        "4": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "5": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
    }
    prepared = ComfyUIImageEditor._prepare_workflow(workflow, "uploaded.png", "make it purple", "no blur", 42, "DPN_EDIT")
    assert prepared["1"]["inputs"]["image"] == "uploaded.png"
    assert prepared["2"]["inputs"]["text"] == "make it purple"
    assert prepared["3"]["inputs"]["text"] == "no blur"
    assert prepared["4"]["inputs"]["seed"] == 42
    assert prepared["5"]["inputs"]["filename_prefix"] == "DPN_EDIT"
    assert workflow["1"]["inputs"]["image"] == "old.png"
