import asyncio

import pytest

from app.deep_research_engine_v10 import EvidenceGraph, EvidenceNode, ResearchClaim, DeepResearchError
from app.deep_research_writer_v10 import DeepResearchWriter
from app.research_intelligence import ResearchSource


class StubWriter:
    def __init__(self, sections):
        self.sections = sections
        self.calls = []

    async def write(self, objective, claims):
        self.calls.append((objective, claims))
        return {"sections": self.sections}


def _add_evidence(graph, *, evidence_id, source_id, workstream="web", quality=0.9, freshness=0.9):
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
        freshness_score=freshness,
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
            freshness_score=freshness,
            metadata={"workstream": workstream},
        )
    )


def test_verified_claims_are_synthesized_with_trusted_citations():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web")
    graph.add_claim(ResearchClaim("claim-1", "Verified finding", ("web-1",), (), 0.8))
    writer = StubWriter([{"title": "Finding", "text": "The finding is supported.", "claim_ids": ["claim-1"]}])

    result = asyncio.run(DeepResearchWriter(writer).synthesize("Assess finding", graph))

    assert result.status == "ready"
    assert result.citation_count == 1
    assert "[cite:claim-1:web-1]" in result.report
    assert result.unresolved_conflicts == ()
    assert writer.calls[0][0] == "Assess finding"
    assert writer.calls[0][1][0]["claim_id"] == "claim-1"
    assert writer.calls[0][1][0]["evidence"][0]["evidence_id"] == "web-1"


def test_disputed_claim_blocks_writer_and_renders_unresolved_conflict_evidence():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="support", source_id="source-support", workstream="web")
    _add_evidence(graph, evidence_id="refute", source_id="source-refute", workstream="documents")
    graph.add_claim(ResearchClaim("claim-1", "Conflicted finding", ("support",), ("refute",), 0.8))
    writer = StubWriter([{"title": "Should not run", "text": "unsafe", "claim_ids": ["claim-1"]}])

    result = asyncio.run(DeepResearchWriter(writer).synthesize("Assess conflict", graph))

    assert result.status == "blocked"
    assert result.report == ""
    assert result.blocked_claims[0]["status"] == "disputed"
    assert result.unresolved_conflicts
    assert writer.calls == []


def test_stale_or_unsupported_claims_block_synthesis_before_writer_call():
    stale = EvidenceGraph()
    _add_evidence(stale, evidence_id="old", source_id="source-old", freshness=0.1)
    stale.add_claim(ResearchClaim("claim-old", "Old finding", ("old",), (), 0.8))
    writer = StubWriter([])
    result = asyncio.run(DeepResearchWriter(writer).synthesize("Assess old finding", stale))
    assert result.status == "blocked"
    assert result.blocked_claims[0]["status"] == "stale"
    assert writer.calls == []


def test_writer_cannot_reference_unknown_or_unverified_claim_ids():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web")
    graph.add_claim(ResearchClaim("claim-1", "Verified finding", ("web-1",), (), 0.8))
    writer = StubWriter([{"title": "Finding", "text": "Attempted provenance invention.", "claim_ids": ["invented"]}])

    with pytest.raises(DeepResearchError, match="unverified claims"):
        asyncio.run(DeepResearchWriter(writer).synthesize("Objective", graph))


def test_writer_must_cover_every_verified_claim_and_each_section_requires_grounding():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web")
    _add_evidence(graph, evidence_id="data-1", source_id="source-data", workstream="data")
    graph.add_claim(ResearchClaim("claim-1", "Finding one", ("web-1",), (), 0.8))
    graph.add_claim(ResearchClaim("claim-2", "Finding two", ("data-1",), (), 0.8))

    omitted = StubWriter([{"title": "One", "text": "Only one finding.", "claim_ids": ["claim-1"]}])
    with pytest.raises(DeepResearchError, match="omitted verified claims"):
        asyncio.run(DeepResearchWriter(omitted).synthesize("Objective", graph))

    ungrounded = StubWriter([{"title": "One", "text": "No grounding.", "claim_ids": []}])
    with pytest.raises(DeepResearchError, match="grounded claim ids"):
        asyncio.run(DeepResearchWriter(ungrounded).synthesize("Objective", graph))


def test_writer_output_type_count_and_length_are_bounded():
    graph = EvidenceGraph()
    _add_evidence(graph, evidence_id="web-1", source_id="source-web")
    graph.add_claim(ResearchClaim("claim-1", "Verified finding", ("web-1",), (), 0.8))

    class BadTypeWriter:
        async def write(self, objective, claims):
            return []

    with pytest.raises(DeepResearchError, match="return an object"):
        asyncio.run(DeepResearchWriter(BadTypeWriter()).synthesize("Objective", graph))

    too_many = StubWriter([
        {"title": f"Section {i}", "text": "Grounded text", "claim_ids": ["claim-1"]}
        for i in range(3)
    ])
    with pytest.raises(DeepResearchError, match="maximum section count"):
        asyncio.run(DeepResearchWriter(too_many, max_sections=2).synthesize("Objective", graph))

    too_long = StubWriter([{"title": "Long", "text": "x" * 129, "claim_ids": ["claim-1"]}])
    with pytest.raises(DeepResearchError, match="maximum length"):
        asyncio.run(DeepResearchWriter(too_long, max_section_chars=128).synthesize("Objective", graph))
