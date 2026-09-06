import pytest

from app.unified_multimodal_runtime_v10 import (
    EvidenceKind,
    Modality,
    MultimodalAsset,
    MultimodalCapabilityPlanner,
    MultimodalEvidence,
    MultimodalEvidenceGate,
    MultimodalRequest,
    MultimodalRouter,
    MultimodalRuntimeError,
    MultimodalSession,
    ProviderCapability,
    ProviderProfile,
)


def test_asset_requires_source_reference():
    with pytest.raises(MultimodalRuntimeError):
        MultimodalAsset("a1", Modality.IMAGE, "").validate()


def test_pdf_without_native_text_requires_document_vision():
    asset = MultimodalAsset("pdf-1", Modality.PDF, "docs/a.pdf")
    required = set(MultimodalCapabilityPlanner.required_for_assets([asset]))
    assert ProviderCapability.DOCUMENT_TEXT in required
    assert ProviderCapability.DOCUMENT_VISION in required


def test_pdf_with_native_text_does_not_force_document_vision():
    asset = MultimodalAsset("pdf-1", Modality.PDF, "docs/a.pdf", native_text="parsed")
    required = set(MultimodalCapabilityPlanner.required_for_assets([asset]))
    assert ProviderCapability.DOCUMENT_TEXT in required
    assert ProviderCapability.DOCUMENT_VISION not in required


def test_audio_without_text_requires_transcription():
    asset = MultimodalAsset("audio-1", Modality.AUDIO, "audio/meeting.wav")
    required = set(MultimodalCapabilityPlanner.required_for_assets([asset]))
    assert ProviderCapability.AUDIO in required
    assert ProviderCapability.TRANSCRIPTION in required


def test_video_requires_video_and_vision():
    asset = MultimodalAsset("video-1", Modality.VIDEO, "video/demo.mp4")
    required = set(MultimodalCapabilityPlanner.required_for_assets([asset]))
    assert ProviderCapability.VIDEO in required
    assert ProviderCapability.VISION in required


def test_router_fails_closed_when_provider_missing_capability():
    profiles = [
        ProviderProfile("local", "text-model", (ProviderCapability.TEXT_REASONING,), local=True),
    ]
    with pytest.raises(MultimodalRuntimeError):
        MultimodalRouter.select(profiles, [ProviderCapability.VISION])


def test_router_prefers_local_when_both_satisfy_request():
    required = (ProviderCapability.TEXT_REASONING, ProviderCapability.VISION)
    profiles = [
        ProviderProfile("remote", "remote-mm", required, local=False),
        ProviderProfile("local", "local-mm", required, local=True),
    ]
    route = MultimodalRouter.select(profiles, required)
    assert route.provider_id == "local"


def test_local_only_rejects_remote_only_provider():
    profiles = [ProviderProfile("remote", "remote-mm", (ProviderCapability.VISION,), local=False)]
    readiness = MultimodalRouter.readiness(profiles, [ProviderCapability.VISION], local_only=True)
    assert readiness.ready is False


def test_session_rejects_evidence_for_unknown_asset():
    session = MultimodalSession("s1")
    with pytest.raises(MultimodalRuntimeError):
        session.add_evidence(MultimodalEvidence("e1", "missing", EvidenceKind.NATIVE_TEXT, "hello"))


def test_visual_request_requires_actual_visual_evidence():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("img-1", Modality.IMAGE, "images/a.png"))
    session.add_evidence(MultimodalEvidence("e1", "img-1", EvidenceKind.METADATA, "1024x1024"))
    request = MultimodalRequest("r1", "inspect image", ("img-1",))
    route = MultimodalRouter.select(
        [ProviderProfile("vision", "vision-model", (ProviderCapability.VISION,))],
        [ProviderCapability.VISION],
    )
    readiness = MultimodalEvidenceGate.evaluate(
        session,
        request,
        route=route,
        cross_checked=True,
        uncertainty_reported=True,
    )
    assert readiness.ready is False
    assert "visual evidence" in readiness.reason


def test_visual_request_requires_provider_model_provenance():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("img-1", Modality.IMAGE, "images/a.png"))
    session.add_evidence(MultimodalEvidence("e1", "img-1", EvidenceKind.VISUAL, "button is disabled"))
    request = MultimodalRequest("r1", "inspect image", ("img-1",))
    route = MultimodalRouter.select(
        [ProviderProfile("vision", "vision-model", (ProviderCapability.VISION,))],
        [ProviderCapability.VISION],
    )
    readiness = MultimodalEvidenceGate.evaluate(
        session,
        request,
        route=route,
        cross_checked=True,
        uncertainty_reported=True,
    )
    assert readiness.ready is False
    assert "provider and model" in readiness.reason


def test_every_requested_asset_must_contribute_evidence():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("text-1", Modality.TEXT, "prompt", native_text="hello"))
    session.add_asset(MultimodalAsset("code-1", Modality.CODE, "app/a.py", native_text="print('x')"))
    session.add_evidence(MultimodalEvidence("e1", "text-1", EvidenceKind.NATIVE_TEXT, "hello"))
    request = MultimodalRequest("r1", "compare", ("text-1", "code-1"))
    route = MultimodalRouter.select(
        [ProviderProfile("local", "combo", (ProviderCapability.TEXT_REASONING, ProviderCapability.CODE), local=True)],
        [ProviderCapability.TEXT_REASONING, ProviderCapability.CODE],
    )
    readiness = MultimodalEvidenceGate.evaluate(
        session,
        request,
        route=route,
        cross_checked=True,
        uncertainty_reported=True,
    )
    assert readiness.ready is False
    assert "every requested asset" in readiness.reason


def test_happy_path_multimodal_evidence_gate_passes():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("img-1", Modality.IMAGE, "images/a.png"))
    session.add_asset(MultimodalAsset("text-1", Modality.TEXT, "prompt", native_text="inspect save button"))
    session.add_evidence(
        MultimodalEvidence(
            "e1",
            "img-1",
            EvidenceKind.VISUAL,
            "save button is disabled",
            provider="vision",
            model="vision-model",
            confidence=0.95,
        )
    )
    session.add_evidence(MultimodalEvidence("e2", "text-1", EvidenceKind.NATIVE_TEXT, "inspect save button"))
    request = MultimodalRequest("r1", "inspect UI", ("img-1", "text-1"))
    required = MultimodalCapabilityPlanner.required_for_assets(session.assets.values())
    route = MultimodalRouter.select(
        [ProviderProfile("vision", "vision-model", tuple(required), local=True)],
        required,
    )
    readiness = MultimodalEvidenceGate.evaluate(
        session,
        request,
        route=route,
        cross_checked=True,
        uncertainty_reported=True,
    )
    assert readiness.ready is True
