import asyncio

import pytest

from app.deep_research_claim_orchestrator_v10 import DeepResearchClaimOrchestrator
from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, EvidenceNode
from app.research_intelligence import ResearchSource


class StubExtractor:
    def __init__(self, claims):
        self.claims = claims
        self.calls = []

    async def extract_claims(self, objective, evidence):
        self.calls.append((objective, evidence))
        return self.claims


def _add_evidence(graph: EvidenceGraph, *, evidence_id: str, source_id: str, workstream: str, quality: float = 0.9):
    source = ResearchSource(
        source_id=source_id,
        title=f"Source {source_id}",
        url=f"https://example.test/{source_id}",
        domain="example.test",
        snippet="evidence",
        content="evidence content",
        published_at=None,
        source_type=workstream,
        authority_score=0.9,
        freshness_score=0.9,
        relevance_score=0.9,
        quality_score=quality,
        metadata={},
    )
    graph.add_source(source)
    graph.add_evidence(
        EvidenceNode(
            evidence_id=evidence_id,
            source_id=source_id,
            source_type=workstream,
            title=source.title,
            locator=source.url,
            excerpt="admitted evidence",
            quality_score=quality,
            freshness_score=0.9,
            metadata={"workstream": workstream},
        )
    )


def test_mixed_workstream_claim_is_admitted_fact_checked_and_cited():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web", workstream="web")
    _add_evidence(graph, evidence_id="data-1", source_id="source-data", workstream="data")
    extractor = StubExtractor(
        [
            {
                "claim_id": "claim-1",
                "text": "The operational finding is corroborated.",
                "supporting_evidence_ids": ["web-1", "data-1"],
                "refuting_evidence_ids": [],
                "confidence": 0.8,
            }
        ]
    )

    result = asyncio.run(
        DeepResearchClaimOrchestrator(extractor).extract_and_assess(
            "Assess the operational finding", graph, require_mixed_workstreams=True
        )
    )

    assert result.claim_count == 1
    assert result.workstreams_used == ("data", "web")
    assert result.fact_checks[0]["status"] == "verified"
    assert result.citation_validation["ok"] is True
    assert result.citation_validation["accepted_count"] == 2
    assert result.readiness["ready"] is True
    assert graph.claim("claim-1") is not None
    assert extractor.calls[0][0] == "Assess the operational finding"
    assert {item["evidence_id"] for item in extractor.calls[0][1]} == {"web-1", "data-1"}


def test_unknown_evidence_rejects_entire_claim_batch_before_graph_mutation():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web", workstream="web")
    extractor = StubExtractor(
        [
            {
                "claim_id": "claim-good",
                "text": "A valid-looking claim.",
                "supporting_evidence_ids": ["web-1"],
                "confidence": 0.8,
            },
            {
                "claim_id": "claim-bad",
                "text": "A claim with invented provenance.",
                "supporting_evidence_ids": ["missing-evidence"],
                "confidence": 0.8,
            },
        ]
    )

    with pytest.raises(DeepResearchError, match="unknown evidence"):
        asyncio.run(DeepResearchClaimOrchestrator(extractor).extract_and_assess("Objective", graph))

    assert graph.claims == ()


def test_claim_id_collision_rejects_batch_transactionally():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web", workstream="web")
    original = StubExtractor(
        [{"claim_id": "claim-1", "text": "Original claim", "supporting_evidence_ids": ["web-1"], "confidence": 0.8}]
    )
    asyncio.run(DeepResearchClaimOrchestrator(original).extract_and_assess("Objective", graph))

    replacement = StubExtractor(
        [{"claim_id": "claim-1", "text": "Changed claim", "supporting_evidence_ids": ["web-1"], "confidence": 0.8}]
    )
    with pytest.raises(DeepResearchError, match="collision"):
        asyncio.run(DeepResearchClaimOrchestrator(replacement).extract_and_assess("Objective", graph))

    assert graph.claim("claim-1").text == "Original claim"


def test_mixed_requirement_fails_closed_when_only_one_workstream_is_referenced():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web", workstream="web")
    extractor = StubExtractor(
        [{"claim_id": "claim-1", "text": "Single stream claim", "supporting_evidence_ids": ["web-1"], "confidence": 0.8}]
    )

    with pytest.raises(DeepResearchError, match="at least two workstreams"):
        asyncio.run(
            DeepResearchClaimOrchestrator(extractor).extract_and_assess(
                "Objective", graph, require_mixed_workstreams=True
            )
        )
    assert graph.claims == ()


def test_refuting_evidence_produces_disputed_readiness_block():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-support", source_id="source-web", workstream="web")
    _add_evidence(graph, evidence_id="doc-refute", source_id="source-doc", workstream="documents")
    extractor = StubExtractor(
        [
            {
                "claim_id": "claim-1",
                "text": "Evidence is in conflict.",
                "supporting_evidence_ids": ["web-support"],
                "refuting_evidence_ids": ["doc-refute"],
                "confidence": 0.8,
            }
        ]
    )

    result = asyncio.run(DeepResearchClaimOrchestrator(extractor).extract_and_assess("Objective", graph))

    assert result.fact_checks[0]["status"] == "disputed"
    assert result.readiness["ready"] is False
    assert result.readiness["blocked_count"] == 1


def test_duplicate_or_unattached_claim_evidence_is_rejected():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web", workstream="web")

    duplicate = StubExtractor(
        [{"claim_id": "claim-1", "text": "Duplicate refs", "supporting_evidence_ids": ["web-1", "web-1"]}]
    )
    with pytest.raises(DeepResearchError, match="duplicate evidence"):
        asyncio.run(DeepResearchClaimOrchestrator(duplicate).extract_and_assess("Objective", graph))

    unattached = StubExtractor([{"claim_id": "claim-2", "text": "No evidence", "confidence": 0.5}])
    with pytest.raises(DeepResearchError, match="require attached evidence"):
        asyncio.run(DeepResearchClaimOrchestrator(unattached).extract_and_assess("Objective", graph))

    assert graph.claims == ()


def test_extractor_bounds_and_type_are_enforced_before_commit():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web", workstream="web")

    class BadExtractor:
        async def extract_claims(self, objective, evidence):
            return {"claim_id": "not-a-sequence"}

    with pytest.raises(DeepResearchError, match="bounded sequence"):
        asyncio.run(DeepResearchClaimOrchestrator(BadExtractor()).extract_and_assess("Objective", graph))

    too_many = StubExtractor(
        [
            {"claim_id": f"claim-{index}", "text": "Claim text", "supporting_evidence_ids": ["web-1"]}
            for index in range(3)
        ]
    )
    with pytest.raises(DeepResearchError, match="maximum claim count"):
        asyncio.run(DeepResearchClaimOrchestrator(too_many, max_claims=2).extract_and_assess("Objective", graph))
    assert graph.claims == ()
