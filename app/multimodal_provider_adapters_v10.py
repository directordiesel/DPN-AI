from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.unified_multimodal_runtime_v10 import MultimodalAsset, MultimodalRuntimeError


class MultimodalAdapterError(MultimodalRuntimeError):
    """Raised when a concrete multimodal provider adapter cannot produce trusted evidence."""


@dataclass(frozen=True)
class AdapterIdentity:
    provider: str
    model: str

    def validate(self) -> None:
        if not self.provider.strip():
            raise MultimodalAdapterError("adapter provider identity is required")
        if not self.model.strip():
            raise MultimodalAdapterError("adapter model identity is required")


class ConfigurableVisionRunnerAdapter:
    """Bind the existing ConfigurableVisionProvider to the v10 coordinator runner contract.

    The wrapped provider remains authoritative for the actual provider/model identity.
    This adapter never substitutes configured identity when the backend fails to report it.
    """

    def __init__(self, provider: Any) -> None:
        if provider is None or not callable(getattr(provider, "analyze", None)):
            raise MultimodalAdapterError("vision adapter requires an analyze-capable provider")
        self.provider = provider

    async def __call__(self, asset: MultimodalAsset, objective: str, model: str) -> dict[str, Any]:
        asset.validate()
        selected_model = str(model or "").strip()
        if not selected_model:
            return {"ok": False, "error": "vision route model is required"}
        result = await self.provider.analyze(
            reference_image=asset.source_ref,
            prompt=str(objective or "Analyze the visual evidence accurately."),
            model=selected_model,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "vision provider returned a non-object result"}
        if not result.get("ok"):
            return result
        provider = str(result.get("provider") or "").strip()
        actual_model = str(result.get("model") or "").strip()
        analysis = str(result.get("analysis") or result.get("content") or "").strip()
        if not provider or not actual_model:
            return {"ok": False, "error": "vision provider omitted provider/model provenance"}
        if not analysis:
            return {"ok": False, "error": "vision provider returned no analysis"}
        payload = dict(result)
        payload.update({"ok": True, "provider": provider, "model": actual_model, "analysis": analysis})
        return payload


class FasterWhisperRunnerAdapter:
    """Bind VoiceAdapter.transcribe to the v10 transcription runner contract.

    faster-whisper is local and synchronous in VoiceAdapter, so execution is moved to a
    worker thread to avoid blocking the async multimodal mission loop. The adapter
    reports the provider as ``faster-whisper`` and preserves the actual model returned
    by VoiceAdapter; it does not relabel fallback models.
    """

    PROVIDER_ID = "faster-whisper"

    def __init__(
        self,
        voice_adapter: Any,
        *,
        language: str | None = None,
        device: str = "auto",
        compute_type: str = "int8",
    ) -> None:
        if voice_adapter is None or not callable(getattr(voice_adapter, "transcribe", None)):
            raise MultimodalAdapterError("whisper adapter requires a transcribe-capable VoiceAdapter")
        self.voice_adapter = voice_adapter
        self.language = language
        self.device = str(device or "auto")
        self.compute_type = str(compute_type or "int8")

    async def __call__(self, asset: MultimodalAsset, model: str) -> dict[str, Any]:
        asset.validate()
        selected_model = str(model or "").strip()
        if not selected_model:
            return {"ok": False, "error": "transcription route model is required"}
        result = await asyncio.to_thread(
            self.voice_adapter.transcribe,
            asset.source_ref,
            selected_model,
            self.language,
            None,
            self.device,
            self.compute_type,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "faster-whisper adapter returned a non-object result"}
        if not result.get("ok"):
            return result
        transcript = str(result.get("text") or "").strip()
        actual_model = str(result.get("model") or "").strip()
        if not transcript:
            return {"ok": False, "error": "faster-whisper returned no transcript"}
        if not actual_model:
            return {"ok": False, "error": "faster-whisper omitted model provenance"}
        probability = result.get("probability")
        confidence: float | None = None
        if probability is not None:
            try:
                confidence = float(probability)
            except (TypeError, ValueError):
                return {"ok": False, "error": "faster-whisper returned invalid language probability"}
            if not 0.0 <= confidence <= 1.0:
                return {"ok": False, "error": "faster-whisper probability must be between 0 and 1"}
        return {
            "ok": True,
            "provider": self.PROVIDER_ID,
            "model": actual_model,
            "transcript": transcript,
            "confidence": confidence,
            "segments": tuple(result.get("segments") or ()),
            "language": result.get("language"),
            "duration": result.get("duration"),
            "elapsed_ms": result.get("elapsed_ms"),
            "path": result.get("path") or asset.source_ref,
        }


__all__ = [
    "AdapterIdentity",
    "ConfigurableVisionRunnerAdapter",
    "FasterWhisperRunnerAdapter",
    "MultimodalAdapterError",
]
