from __future__ import annotations

import pytest

from app.deep_research_engine_v10 import (
    CitationReference,
    CitationValidator,
    ClaimStatus,
    DeepResearchError,
    DeepResearchReadinessGate,
    EvidenceGraph,
    EvidenceNode,
    ResearchClaim,
    ResearchConflictDetector,
    ResearchDirector,
    ResearchFactChecker,
    ResearchWorkstream,
)
from app.research_intelligence import ResearchSource


def source(source_id: str, *, quality: float = 0.9, freshness: float = 0.9) -> ResearchSource:
    return ResearchSource(
        source_id=source_id,
        title=f"Source {source_id}",
        url=f"https://example.com/{source_id}",
        domain="example.com",
        source_type="web",
        quality_score=quality,
        freshness_score=freshness,
        authority_score=quality,
        relevance_score=quality,
    )


def evidence(evidence_id: str, source_id: str, *, quality: float = 0.9, freshness: float = 0.9) -> EvidenceNode:
    return EvidenceNode(
        evidence_id=evidence_id,
        source_id=source_id,
        source_type="web",
        title=f"Evidence {evidence_id}",
        locator=f"https://example.com/{source_id}#fact",
        excerpt="A bounded factual excerpt supporting the claim.",
        quality_score=quality,
        freshness_score=freshness,
    )


def graph_with_support(*, quality: float = 0.9, freshness: float = 0.9) -> EvidenceGraph:
    graph = EvidenceGraph()
    graph.add_source(source("s1", quality=quality, freshness=freshness))
    graph.add_evidence(evidence("e1", "s1", quality=quality, freshness=freshness))
    graph.add_claim(ResearchClaim(
        claim_id="c1",
        text="The system passed the required verification gate.",
        supporting_evidence_ids=("e1",),
        confidence=0.8,
    ))
    return graph


def test_director_builds_bounded_three_stream_plan():
    plan = ResearchDirector().plan("Compare current system reliability evidence")
    assert [task.workstream for task in plan.tasks] == [
        ResearchWorkstream.WEB,
        ResearchWorkstream.DOCUMENTS,
        ResearchWorkstream.DATA,
    ]
    assert plan.tasks[0].required is True
    assert plan.tasks[1].required is False
    assert plan.tasks[2].required is False


def test_director_rejects_empty_objective_and_empty_configuration():
    with pytest.raises(DeepResearchError, match="objective"):
        ResearchDirector().plan("  ")
    with pytest.raises(DeepResearchError, match="at least one task"):
        ResearchDirector(include_web=False, include_documents=False, include_data=False).plan("test")


def test_evidence_graph_requires_known_source_and_known_evidence():
    graph = EvidenceGraph()
    with pytest.raises(DeepResearchError, match="unknown source"):
        graph.add_evidence(evidence("e1", "missing"))
    graph.add_source(source("s1"))
    graph.add_evidence(evidence("e1", "s1"))
    with pytest.raises(DeepResearchError, match="unknown evidence"):
        graph.add_claim(ResearchClaim("c1", "Claim", supporting_evidence_ids=("e2",)))


def test_evidence_graph_rejects_support_refute_overlap():
    graph = EvidenceGraph()
    graph.add_source(source("s1"))
    graph.add_evidence(evidence("e1", "s1"))
    with pytest.raises(DeepResearchError, match="both support and refute"):
        graph.add_claim(ResearchClaim(
            "c1",
            "Claim",
            supporting_evidence_ids=("e1",),
            refuting_evidence_ids=("e1",),
        ))


def test_fact_checker_verifies_supported_current_claim():
    result = ResearchFactChecker().check(graph_with_support(), "c1")
    assert result.status == ClaimStatus.VERIFIED
    assert result.supporting_evidence_ids == ("e1",)
    assert result.refuting_evidence_ids == ()


def test_fact_checker_fails_closed_on_low_quality_support():
    result = ResearchFactChecker(minimum_quality=0.6).check(graph_with_support(quality=0.4), "c1")
    assert result.status == ClaimStatus.UNSUPPORTED
    assert result.confidence == 0.0


def test_fact_checker_marks_all_stale_support_stale():
    result = ResearchFactChecker(stale_freshness=0.2).check(graph_with_support(freshness=0.1), "c1")
    assert result.status == ClaimStatus.STALE


def test_fact_checker_marks_qualified_support_and_refutation_disputed():
    graph = graph_with_support()
    graph.add_source(source("s2"))
    graph.add_evidence(EvidenceNode(
        evidence_id="e2",
        source_id="s2",
        source_type="web",
        title="Refutation",
        locator="https://example.com/s2#fact",
        excerpt="A qualified source directly refutes the same claim.",
        quality_score=0.9,
        freshness_score=0.9,
    ))
    graph = EvidenceGraph()
    graph.add_source(source("s1"))
    graph.add_source(source("s2"))
    graph.add_evidence(evidence("e1", "s1"))
    graph.add_evidence(EvidenceNode(
        evidence_id="e2",
        source_id="s2",
        source_type="web",
        title="Refutation",
        locator="https://example.com/s2#fact",
        excerpt="A qualified source directly refutes the same claim.",
        quality_score=0.9,
        freshness_score=0.9,
    ))
    graph.add_claim(ResearchClaim(
        "c1",
        "The system passed the required verification gate.",
        supporting_evidence_ids=("e1",),
        refuting_evidence_ids=("e2",),
        confidence=0.9,
    ))
    result = ResearchFactChecker().check(graph, "c1")
    assert result.status == ClaimStatus.DISPUTED


def test_conflict_detector_reuses_mature_claim_conflict_logic():
    graph = EvidenceGraph()
    graph.add_source(source("s1"))
    graph.add_source(source("s2"))
    graph.add_evidence(evidence("e1", "s1"))
    graph.add_evidence(EvidenceNode(
        evidence_id="e2",
        source_id="s2",
        source_type="web",
        title="Refutation",
        locator="https://example.com/s2#fact",
        excerpt="Refuting evidence.",
        quality_score=0.9,
        freshness_score=0.9,
    ))
    graph.add_claim(ResearchClaim(
        "c1",
        "Deployment completed successfully.",
        supporting_evidence_ids=("e1",),
        refuting_evidence_ids=("e2",),
        confidence=0.9,
    ))
    conflicts = ResearchConflictDetector.detect(graph)
    assert conflicts[0]["status"] == "conflict"
    assert set(conflicts[0]["stances"]) == {"supports", "refutes"}


def test_citation_validator_accepts_attached_evidence_and_rejects_mismatch():
    graph = graph_with_support()
    graph.add_source(source("s2"))
    graph.add_evidence(evidence("e2", "s2"))
    result = CitationValidator().validate(graph, [
        CitationReference("R1", "c1", "e1"),
        CitationReference("R2", "c1", "e2"),
    ])
    assert result["ok"] is False
    assert result["accepted_count"] == 1
    assert result["rejected"] == [{"citation_id": "R2", "reason": "evidence_not_attached_to_claim"}]


def test_citation_validator_rejects_duplicate_citation_ids():
    graph = graph_with_support()
    result = CitationValidator().validate(graph, [
        CitationReference("R1", "c1", "e1"),
        CitationReference("R1", "c1", "e1"),
    ])
    assert result["ok"] is False
    assert result["accepted_count"] == 1
    assert result["rejected"][0]["reason"] == "invalid_or_duplicate_citation_id"


def test_readiness_requires_all_claims_verified_and_no_conflicts():
    ready = DeepResearchReadinessGate().evaluate(graph_with_support())
    assert ready["ready"] is True
    assert ready["verified_count"] == 1

    stale = DeepResearchReadinessGate().evaluate(graph_with_support(freshness=0.1))
    assert stale["ready"] is False
    assert stale["blocked_count"] == 1
    assert stale["claims"][0]["status"] == "stale"


def test_empty_graph_is_not_research_ready():
    result = DeepResearchReadinessGate().evaluate(EvidenceGraph())
    assert result["ready"] is False
    assert result["claim_count"] == 0
