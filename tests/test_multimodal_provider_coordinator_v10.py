from __future__ import annotations

import pytest

from app.multimodal_provider_coordinator_v10 import (
    MultimodalProviderCoordinator,
    ProviderExecutionError,
)
from app.unified_multimodal_runtime_v10 import (
    EvidenceKind,
    Modality,
    MultimodalAsset,
    MultimodalEvidence,
    MultimodalRequest,
    MultimodalSession,
    ProviderCapability,
    ProviderProfile,
)


def profile(*caps: ProviderCapability, local: bool = True) -> ProviderProfile:
    return ProviderProfile("provider-1", "model-1", caps, configured=True, healthy=True, local=local)


def session_with_image() -> MultimodalSession:
    session = MultimodalSession("session-1")
    session.add_asset(MultimodalAsset("img-1", Modality.IMAGE, "images/a.png", sha256="abc", mime_type="image/png"))
    return session


@pytest.mark.asyncio
async def test_image_execution_records_provider_backed_visual_evidence_and_fuses() -> None:
    async def vision(asset, objective, model):
        assert asset.asset_id == "img-1"
        assert objective == "inspect image"
        assert model == "model-1"
        return {
            "ok": True,
            "analysis": "A purple dashboard is visible.",
            "provider": "provider-1",
            "model": "model-1",
            "confidence": 0.92,
        }

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False)
    result = await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)

    assert result.readiness.ready is True
    assert result.fusion.verified is True
    assert len(result.provider_results) == 1
    evidence = session.evidence[-1]
    assert evidence.kind == EvidenceKind.VISUAL
    assert evidence.provider == "provider-1"
    assert evidence.model == "model-1"


@pytest.mark.asyncio
async def test_image_execution_fails_closed_without_vision_runner() -> None:
    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)])
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False)
    with pytest.raises(ProviderExecutionError, match="no vision runner"):
        await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)


@pytest.mark.asyncio
async def test_failed_vision_payload_does_not_create_evidence() -> None:
    async def vision(_asset, _objective, _model):
        return {"ok": False, "error": "vision backend unavailable"}

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False)
    with pytest.raises(ProviderExecutionError, match="vision backend unavailable"):
        await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)
    assert session.evidence == []


@pytest.mark.asyncio
async def test_provider_must_report_actual_provenance() -> None:
    async def vision(_asset, _objective, _model):
        return {"ok": True, "analysis": "Visible dashboard."}

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False)
    with pytest.raises(ProviderExecutionError, match="explicitly report provider and model"):
        await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)
    assert session.evidence == []


@pytest.mark.asyncio
async def test_silent_provider_or_model_fallback_is_rejected() -> None:
    async def vision(_asset, _objective, _model):
        return {
            "ok": True,
            "analysis": "Visible dashboard.",
            "provider": "fallback-provider",
            "model": "fallback-model",
        }

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False)
    with pytest.raises(ProviderExecutionError, match="does not match the selected route"):
        await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)
    assert session.evidence == []


@pytest.mark.asyncio
async def test_multi_asset_execution_is_transactional_on_late_failure() -> None:
    calls = 0

    async def vision(asset, _objective, _model):
        nonlocal calls
        calls += 1
        if asset.asset_id == "img-2":
            return {"ok": False, "error": "second image failed"}
        return {
            "ok": True,
            "analysis": "First image visible.",
            "provider": "provider-1",
            "model": "model-1",
        }

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    session.add_asset(MultimodalAsset("img-2", Modality.IMAGE, "images/b.png", sha256="def", mime_type="image/png"))
    request = MultimodalRequest("r1", "compare images", ("img-1", "img-2"), require_cross_check=False)
    with pytest.raises(ProviderExecutionError, match="second image failed"):
        await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)
    assert calls == 2
    assert session.evidence == []


@pytest.mark.asyncio
async def test_existing_route_evidence_is_reused_without_provider_call() -> None:
    called = False

    async def vision(_asset, _objective, _model):
        nonlocal called
        called = True
        raise AssertionError("runner should not be called")

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    session.add_evidence(
        MultimodalEvidence(
            "img-1:visual:1",
            "img-1",
            EvidenceKind.VISUAL,
            "Existing visual evidence.",
            provider="provider-1",
            model="model-1",
        )
    )
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False)
    result = await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)
    assert called is False
    assert len(session.evidence) == 1
    assert result.provider_results[0].reason.startswith("existing")
    assert result.fusion.verified is True


@pytest.mark.asyncio
async def test_audio_transcription_is_recorded_with_provenance() -> None:
    async def transcribe(asset, model):
        assert asset.asset_id == "audio-1"
        assert model == "model-1"
        return {
            "ok": True,
            "transcript": "System check complete.",
            "provider": "provider-1",
            "model": "model-1",
            "confidence": 0.88,
        }

    coordinator = MultimodalProviderCoordinator(
        [profile(ProviderCapability.AUDIO, ProviderCapability.TRANSCRIPTION)],
        transcription_runner=transcribe,
    )
    session = MultimodalSession("session-1")
    session.add_asset(MultimodalAsset("audio-1", Modality.AUDIO, "audio/check.wav", sha256="def", mime_type="audio/wav"))
    request = MultimodalRequest("r1", "transcribe", ("audio-1",), require_cross_check=False)
    result = await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)

    assert result.readiness.ready is True
    assert result.fusion.verified is True
    assert session.evidence[-1].kind == EvidenceKind.TRANSCRIPT


@pytest.mark.asyncio
async def test_native_text_asset_uses_existing_evidence_without_extra_provider_call() -> None:
    called = False

    async def vision(_asset, _objective, _model):
        nonlocal called
        called = True
        return {"ok": True, "analysis": "unexpected", "provider": "provider-1", "model": "model-1"}

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.DOCUMENT_TEXT)], vision_runner=vision)
    session = MultimodalSession("session-1")
    session.add_asset(MultimodalAsset("pdf-1", Modality.PDF, "docs/a.pdf", native_text="Native text"))
    session.add_evidence(MultimodalEvidence("native-1", "pdf-1", EvidenceKind.NATIVE_TEXT, "Native text"))
    request = MultimodalRequest("r1", "read pdf", ("pdf-1",), require_cross_check=False)
    result = await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)

    assert called is False
    assert result.provider_results == ()
    assert result.readiness.ready is True
    assert result.fusion.verified is True


@pytest.mark.asyncio
async def test_local_only_request_rejects_remote_only_profile() -> None:
    coordinator = MultimodalProviderCoordinator(
        [profile(ProviderCapability.VISION, local=False)],
        vision_runner=lambda *_args: None,  # never reached
    )
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=False, local_only=True)
    with pytest.raises(Exception, match="no configured healthy provider"):
        await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)


@pytest.mark.asyncio
async def test_cross_check_gate_can_keep_fusion_unverified() -> None:
    async def vision(_asset, _objective, _model):
        return {"ok": True, "analysis": "A dashboard is visible.", "provider": "provider-1", "model": "model-1"}

    coordinator = MultimodalProviderCoordinator([profile(ProviderCapability.VISION)], vision_runner=vision)
    session = session_with_image()
    request = MultimodalRequest("r1", "inspect image", ("img-1",), require_cross_check=True)
    result = await coordinator.execute(session, request, cross_checked=False, uncertainty_reported=True)

    assert result.readiness.ready is False
    assert result.fusion.verified is False
    assert "cross-check" in result.fusion.reason
