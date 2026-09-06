import pytest

from app.multimodal_fusion_v10 import ClaimStatus, FusionError, MultimodalFusionEngine
from app.unified_multimodal_runtime_v10 import (
    EvidenceKind,
    Modality,
    MultimodalAsset,
    MultimodalEvidence,
    MultimodalRequest,
    MultimodalSession,
    RouteDecision,
    ProviderCapability,
)


def route() -> RouteDecision:
    return RouteDecision(
        provider_id="vision-local",
        model="dpn-mm",
        required_capabilities=(ProviderCapability.VISION,),
        reason="test route",
    )


def test_fusion_preserves_page_provenance_and_verifies_native_document():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("a1", Modality.PDF, "docs/report.pdf", page=2, native_text="Revenue grew."))
    session.add_evidence(MultimodalEvidence("e1", "a1", EvidenceKind.NATIVE_TEXT, "Revenue grew."))
    request = MultimodalRequest("r1", "summarize", ("a1",), require_cross_check=False)
    context = MultimodalFusionEngine.build_context(
        session,
        request,
        route=route(),
        cross_checked=False,
        uncertainty_reported=True,
    )
    assert context.verified
    assert context.claims[0].provenance[0].page == 2


def test_visual_asset_requires_visual_evidence():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("img", Modality.IMAGE, "images/a.png"))
    session.add_evidence(MultimodalEvidence("e1", "img", EvidenceKind.METADATA, "image/png"))
    request = MultimodalRequest("r1", "inspect", ("img",), require_cross_check=False)
    context = MultimodalFusionEngine.build_context(
        session,
        request,
        route=route(),
        cross_checked=False,
        uncertainty_reported=True,
    )
    assert not context.verified
    assert "visual evidence" in context.reason


def test_visual_evidence_requires_provider_model_provenance():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("img", Modality.IMAGE, "images/a.png"))
    session.add_evidence(MultimodalEvidence("e1", "img", EvidenceKind.VISUAL, "A red square."))
    request = MultimodalRequest("r1", "inspect", ("img",), require_cross_check=False)
    context = MultimodalFusionEngine.build_context(
        session,
        request,
        route=route(),
        cross_checked=False,
        uncertainty_reported=True,
    )
    assert not context.verified
    assert "provider and model" in context.reason


def test_provider_backed_visual_evidence_verifies():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("img", Modality.IMAGE, "images/a.png"))
    session.add_evidence(
        MultimodalEvidence(
            "e1",
            "img",
            EvidenceKind.VISUAL,
            "A red square.",
            provider="vision-local",
            model="dpn-mm",
            confidence=0.92,
        )
    )
    request = MultimodalRequest("r1", "inspect", ("img",), require_cross_check=False)
    context = MultimodalFusionEngine.build_context(
        session,
        request,
        route=route(),
        cross_checked=False,
        uncertainty_reported=True,
    )
    assert context.verified
    assert context.claims[0].confidence == 0.92


def test_structured_conflict_blocks_verified_completion():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("sheet", Modality.SPREADSHEET, "data/book.xlsx"))
    session.add_evidence(MultimodalEvidence("e1", "sheet", EvidenceKind.TABLE, "Total=100"))
    session.add_evidence(MultimodalEvidence("e2", "sheet", EvidenceKind.TABLE, "Total=200"))
    request = MultimodalRequest("r1", "compare totals", ("sheet",), require_cross_check=False)
    context = MultimodalFusionEngine.build_context(
        session,
        request,
        route=route(),
        cross_checked=False,
        uncertainty_reported=True,
    )
    assert not context.verified
    assert context.conflicts
    assert all(claim.status == ClaimStatus.CONFLICTED for claim in context.claims)


def test_cross_check_gate_is_enforced():
    session = MultimodalSession("s1")
    session.add_asset(MultimodalAsset("a1", Modality.TEXT, "notes.txt", native_text="hello"))
    session.add_evidence(MultimodalEvidence("e1", "a1", EvidenceKind.NATIVE_TEXT, "hello"))
    request = MultimodalRequest("r1", "read", ("a1",), require_cross_check=True)
    context = MultimodalFusionEngine.build_context(
        session,
        request,
        route=route(),
        cross_checked=False,
        uncertainty_reported=True,
    )
    assert not context.verified
    assert "cross-check" in context.reason


def test_missing_asset_fails_closed():
    session = MultimodalSession("s1")
    request = MultimodalRequest("r1", "read", ("missing",), require_cross_check=False)
    with pytest.raises(FusionError):
        MultimodalFusionEngine.build_context(
            session,
            request,
            route=route(),
            cross_checked=False,
            uncertainty_reported=True,
        )
