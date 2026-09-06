from __future__ import annotations

import asyncio

import pytest

from app.multimodal_provider_adapters_v10 import (
    ConfigurableVisionRunnerAdapter,
    FasterWhisperRunnerAdapter,
    MultimodalAdapterError,
)
from app.unified_multimodal_runtime_v10 import Modality, MultimodalAsset


class FakeVisionProvider:
    async def analyze(self, reference_image: str, prompt: str, model: str):
        return {
            "ok": True,
            "provider": "vision-gateway",
            "model": model,
            "analysis": f"observed {reference_image}: {prompt}",
            "confidence": 0.91,
        }


class FakeVoiceAdapter:
    def __init__(self, result=None):
        self.result = result or {
            "ok": True,
            "text": "hello from audio",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello from audio"}],
            "language": "en",
            "probability": 0.97,
            "duration": 1.0,
            "model": "base",
            "elapsed_ms": 20,
            "path": "uploads/voice/test.wav",
        }
        self.calls = []

    def transcribe(self, path, model_size, language, initial_prompt, device, compute_type):
        self.calls.append((path, model_size, language, initial_prompt, device, compute_type))
        return self.result


def asset(modality: Modality, source_ref: str = "uploads/test.bin") -> MultimodalAsset:
    return MultimodalAsset(asset_id="a1", modality=modality, source_ref=source_ref)


def test_vision_adapter_preserves_actual_backend_identity():
    runner = ConfigurableVisionRunnerAdapter(FakeVisionProvider())
    result = asyncio.run(runner(asset(Modality.IMAGE, "uploads/image.png"), "inspect image", "vision-model"))
    assert result["ok"] is True
    assert result["provider"] == "vision-gateway"
    assert result["model"] == "vision-model"
    assert "uploads/image.png" in result["analysis"]


def test_vision_adapter_fails_closed_when_provenance_is_missing():
    class BadProvider:
        async def analyze(self, **kwargs):
            return {"ok": True, "analysis": "looks fine"}

    result = asyncio.run(
        ConfigurableVisionRunnerAdapter(BadProvider())(
            asset(Modality.IMAGE, "uploads/image.png"), "inspect", "vision-model"
        )
    )
    assert result["ok"] is False
    assert "provenance" in result["error"]


def test_whisper_adapter_maps_voice_adapter_to_coordinator_contract():
    voice = FakeVoiceAdapter()
    runner = FasterWhisperRunnerAdapter(voice, language="en", device="cpu", compute_type="int8")
    result = asyncio.run(runner(asset(Modality.AUDIO, "uploads/voice/test.wav"), "base"))
    assert result["ok"] is True
    assert result["provider"] == "faster-whisper"
    assert result["model"] == "base"
    assert result["transcript"] == "hello from audio"
    assert result["confidence"] == 0.97
    assert voice.calls == [("uploads/voice/test.wav", "base", "en", None, "cpu", "int8")]


def test_whisper_adapter_rejects_model_provenance_omission():
    voice = FakeVoiceAdapter({"ok": True, "text": "hello", "model": ""})
    result = asyncio.run(FasterWhisperRunnerAdapter(voice)(asset(Modality.AUDIO, "audio.wav"), "base"))
    assert result["ok"] is False
    assert "model provenance" in result["error"]


def test_whisper_adapter_rejects_invalid_probability():
    voice = FakeVoiceAdapter({"ok": True, "text": "hello", "model": "base", "probability": 4.2})
    result = asyncio.run(FasterWhisperRunnerAdapter(voice)(asset(Modality.AUDIO, "audio.wav"), "base"))
    assert result["ok"] is False
    assert "between 0 and 1" in result["error"]


def test_adapters_require_compatible_backends():
    with pytest.raises(MultimodalAdapterError):
        ConfigurableVisionRunnerAdapter(object())
    with pytest.raises(MultimodalAdapterError):
        FasterWhisperRunnerAdapter(object())
