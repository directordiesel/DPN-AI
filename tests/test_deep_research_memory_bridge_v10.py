import pytest

from app.advanced_layered_memory_v10 import MemoryContext, MemoryLayer
from app.deep_research_engine_v10 import EvidenceGraph, EvidenceNode, ResearchClaim
from app.deep_research_memory_bridge_v10 import DeepResearchMemoryBridge
from app.deep_research_mission_v10 import DeepResearchMissionResult
from app.research_intelligence import ResearchSource


class RecordingMemory:
    def __init__(self, *, fail_at: int | None = None):
        self.requests = []
        self.fail_at = fail_at

    async def remember(self, request):
        self.requests.append(request)
        if self.fail_at is not None and len(self.requests) == self.fail_at:
            return {"ok": False, "stored": False, "error": "forced failure"}
        return {"ok": True, "stored": True, "memory_id": f"m{len(self.requests)}"}


def build_graph(*, disputed: bool = False):
    graph = EvidenceGraph()
    graph.add_source(ResearchSource(
        source_id="src-web",
        title="Primary source",
        url="https://example.com/source",
        domain="example.com",
        source_type="web",
        quality_score=0.9,
        freshness_score=0.9,
    ))
    graph.add_evidence(EvidenceNode(
        evidence_id="ev-1",
        source_id="src-web",
        source_type="web",
        title="Primary source",
        locator="https://example.com/source#one",
        excerpt="Verified evidence one",
        quality_score=0.9,
        freshness_score=0.9,
        metadata={"workstream": "web"},
    ))
    if disputed:
        graph.add_evidence(EvidenceNode(
            evidence_id="ev-2",
            source_id="src-web",
            source_type="web",
            title="Primary source",
            locator="https://example.com/source#two",
            excerpt="Refuting evidence",
            quality_score=0.9,
            freshness_score=0.9,
            metadata={"workstream": "web"},
        ))
    graph.add_claim(ResearchClaim(
        claim_id="claim-1",
        text="The verified research claim.",
        supporting_evidence_ids=("ev-1",),
        refuting_evidence_ids=("ev-2",) if disputed else (),
        confidence=0.88,
    ))
    return graph


def mission(*, status="ready", release_ready=True, citation_ok=True, fact_status="verified"):
    return DeepResearchMissionResult(
        status=status,
        objective="Assess the system readiness",
        task_results=(),
        task_failures=(),
        graph_summary={"source_count": 1, "evidence_count": 1, "claim_count": 1},
        claim_assessment={
            "fact_checks": [{
                "claim_id": "claim-1",
                "status": fact_status,
                "confidence": 0.91,
                "supporting_evidence_ids": ["ev-1"],
                "refuting_evidence_ids": [],
            }],
            "citation_validation": {"ok": citation_ok},
            "readiness": {"ready": release_ready},
        },
        synthesis={"status": "ready", "report": "Grounded final research report."},
        release_readiness={"release_ready": release_ready},
    )


@pytest.mark.asyncio
async def test_ingests_verified_claim_then_episode_with_trusted_evidence():
    memory = RecordingMemory()
    bridge = DeepResearchMemoryBridge(memory)

    result = await bridge.ingest(
        mission(),
        build_graph(),
        context=MemoryContext(organization_id="dpn", project_id="dpn-ai"),
    )

    assert result.ok is True
    assert result.semantic_stored == 1
    assert result.episode_stored is True
    assert len(memory.requests) == 2

    semantic, episode = memory.requests
    assert semantic.layer == MemoryLayer.SEMANTIC
    assert semantic.provenance.evidence_ids == ("ev-1",)
    assert semantic.provenance.source_type == "deep_research"
    assert semantic.content == "The verified research claim."
    assert semantic.provenance.authority == pytest.approx(0.9)

    assert episode.layer == MemoryLayer.EPISODIC
    assert episode.provenance.evidence_ids == ("ev-1",)
    assert "Grounded final research report." in episode.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        mission(status="partial", release_ready=False),
        mission(citation_ok=False),
        mission(fact_status="disputed"),
    ],
)
async def test_non_release_ready_or_unverified_research_never_mutates_memory(result):
    memory = RecordingMemory()
    bridge = DeepResearchMemoryBridge(memory)

    receipt = await bridge.ingest(result, build_graph(), context=MemoryContext(project_id="dpn-ai"))

    assert receipt.ok is False
    assert receipt.semantic_stored == 0
    assert memory.requests == []


@pytest.mark.asyncio
async def test_graph_claim_missing_from_fact_check_set_fails_closed_before_write():
    graph = build_graph()
    graph.add_claim(ResearchClaim(
        claim_id="claim-2",
        text="A second graph claim.",
        supporting_evidence_ids=("ev-1",),
        confidence=0.8,
    ))
    memory = RecordingMemory()

    result = await DeepResearchMemoryBridge(memory).ingest(
        mission(), graph, context=MemoryContext(project_id="dpn-ai")
    )

    assert result.ok is False
    assert "exactly cover" in result.errors[0]["error"]
    assert memory.requests == []


@pytest.mark.asyncio
async def test_unknown_fact_check_claim_fails_closed_before_write():
    result = mission()
    result.claim_assessment["fact_checks"][0]["claim_id"] = "invented-claim"
    memory = RecordingMemory()

    receipt = await DeepResearchMemoryBridge(memory).ingest(
        result, build_graph(), context=MemoryContext(project_id="dpn-ai")
    )

    assert receipt.ok is False
    assert "absent from the trusted evidence graph" in receipt.errors[0]["error"]
    assert memory.requests == []


@pytest.mark.asyncio
async def test_semantic_write_failure_prevents_episode_write():
    memory = RecordingMemory(fail_at=1)
    bridge = DeepResearchMemoryBridge(memory)

    result = await bridge.ingest(
        mission(), build_graph(), context=MemoryContext(project_id="dpn-ai")
    )

    assert result.ok is False
    assert result.semantic_stored == 0
    assert result.episode_stored is False
    assert len(memory.requests) == 1
    assert memory.requests[0].layer == MemoryLayer.SEMANTIC


@pytest.mark.asyncio
async def test_sensitive_flag_is_forwarded_to_existing_memory_approval_boundary():
    memory = RecordingMemory()
    bridge = DeepResearchMemoryBridge(memory)

    result = await bridge.ingest(
        mission(),
        build_graph(),
        context=MemoryContext(user_id="diesel", project_id="dpn-ai"),
        sensitive=True,
    )

    assert result.ok is True
    assert all(request.sensitive is True for request in memory.requests)


@pytest.mark.asyncio
async def test_episode_failure_is_explicit_after_semantic_success():
    memory = RecordingMemory(fail_at=2)
    bridge = DeepResearchMemoryBridge(memory)

    result = await bridge.ingest(
        mission(), build_graph(), context=MemoryContext(project_id="dpn-ai")
    )

    assert result.ok is False
    assert result.release_ready is True
    assert result.semantic_stored == 1
    assert result.episode_stored is False
    assert result.errors[0]["stage"] == "episode"
