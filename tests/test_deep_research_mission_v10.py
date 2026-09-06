import asyncio
from dataclasses import dataclass

import pytest

from app.deep_research_claim_orchestrator_v10 import DeepResearchClaimOrchestrator
from app.deep_research_data_worker_v10 import DataQuerySpec
from app.deep_research_engine_v10 import DeepResearchError, EvidenceNode
from app.deep_research_mission_v10 import (
    DeepResearchMissionOrchestrator,
    DeepResearchMissionRequest,
)
from app.deep_research_writer_v10 import DeepResearchWriter
from app.research_intelligence import ResearchSource


@dataclass(frozen=True)
class FakeWorkerResult:
    task_id: str
    evidence_count: int


class FakeWorker:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    async def execute(self, task, graph):
        self.calls.append(task.task_id)
        if self.fail:
            raise DeepResearchError(f"{task.workstream.value} worker unavailable")
        source_id = f"source-{task.workstream.value}"
        evidence_id = f"evidence-{task.workstream.value}"
        source = ResearchSource(
            source_id=source_id,
            title=source_id,
            url=f"https://example.test/{source_id}",
            domain="example.test",
            snippet="evidence",
            content="evidence content",
            source_type=task.workstream.value,
            authority_score=0.9,
            freshness_score=0.9,
            relevance_score=0.9,
            quality_score=0.9,
            metadata={},
        )
        graph.add_source(source)
        graph.add_evidence(
            EvidenceNode(
                evidence_id=evidence_id,
                source_id=source_id,
                source_type=task.workstream.value,
                title=source_id,
                locator=source.url,
                excerpt=f"trusted {task.workstream.value} evidence",
                quality_score=0.9,
                freshness_score=0.9,
                metadata={"task_id": task.task_id, "workstream": task.workstream.value},
            )
        )
        return FakeWorkerResult(task.task_id, 1)


class FakeDataWorker:
    def __init__(self):
        self.calls = []

    async def execute(self, task, graph, spec):
        self.calls.append((task.task_id, spec.table))
        source = ResearchSource(
            source_id="source-data",
            title="data",
            url="dpn://connector/sqlite/test/operation_runs",
            domain="local.dpn",
            snippet="row",
            content="row",
            source_type="structured_data",
            authority_score=0.9,
            freshness_score=0.9,
            relevance_score=0.9,
            quality_score=0.9,
            metadata={},
        )
        graph.add_source(source)
        graph.add_evidence(
            EvidenceNode(
                evidence_id="evidence-data",
                source_id="source-data",
                source_type="structured_data",
                title="row",
                locator="sqlite://test/operation_runs#row-1",
                excerpt="{\"status\":\"success\"}",
                quality_score=0.9,
                freshness_score=0.9,
                metadata={"task_id": task.task_id, "workstream": "data", "read_only": True},
            )
        )
        return FakeWorkerResult(task.task_id, 1)


class EvidenceClaimExtractor:
    def __init__(self):
        self.calls = []

    async def extract_claims(self, objective, evidence):
        self.calls.append((objective, evidence))
        return [
            {
                "claim_id": "claim-1",
                "text": "The admitted evidence supports the finding.",
                "supporting_evidence_ids": [item["evidence_id"] for item in evidence],
                "refuting_evidence_ids": [],
                "confidence": 0.9,
            }
        ]


class StubWriter:
    def __init__(self):
        self.calls = []

    async def write(self, objective, claims):
        self.calls.append((objective, claims))
        return {
            "sections": [
                {
                    "title": "Finding",
                    "text": "The finding is supported by the admitted evidence.",
                    "claim_ids": ["claim-1"],
                }
            ]
        }


def _mission(*, web=None, documents=None, data=None):
    extractor = EvidenceClaimExtractor()
    writer = StubWriter()
    return (
        DeepResearchMissionOrchestrator(
            web_worker=web,
            document_worker=documents,
            data_worker=data,
            claim_orchestrator=DeepResearchClaimOrchestrator(extractor),
            writer=DeepResearchWriter(writer),
        ),
        extractor,
        writer,
    )


def test_full_web_documents_data_mission_reaches_release_readiness():
    web = FakeWorker()
    documents = FakeWorker()
    data = FakeDataWorker()
    mission, extractor, writer = _mission(web=web, documents=documents, data=data)

    result = asyncio.run(
        mission.run(
            DeepResearchMissionRequest(
                objective="Assess operational readiness",
                require_mixed_workstreams=True,
                data_queries={"data-primary": DataQuerySpec(table="operation_runs", limit=10)},
            )
        )
    )

    assert result.status == "ready"
    assert result.release_readiness["release_ready"] is True
    assert result.release_readiness["completed_workstreams"] == ["data", "documents", "web"]
    assert result.graph_summary == {
        "source_count": 3,
        "evidence_count": 3,
        "claim_count": 1,
        "workstreams_with_evidence": ["data", "documents", "web"],
    }
    assert result.claim_assessment["readiness"]["ready"] is True
    assert result.synthesis["status"] == "ready"
    assert result.synthesis["citation_count"] == 3
    assert len(extractor.calls[0][1]) == 3
    assert writer.calls


def test_optional_worker_failure_is_explicit_and_prevents_release_ready_upgrade():
    web = FakeWorker()
    documents = FakeWorker(fail=True)
    mission, _, writer = _mission(web=web, documents=documents, data=None)

    result = asyncio.run(
        mission.run(
            DeepResearchMissionRequest(
                objective="Research with an optional local source",
                include_data=False,
            )
        )
    )

    assert result.status == "partial"
    assert result.release_readiness["release_ready"] is False
    assert result.release_readiness["optional_failure_count"] == 1
    assert result.release_readiness["failed_workstreams"] == ["documents"]
    assert result.task_failures[0]["required"] is False
    assert result.task_failures[0]["error_type"] == "DeepResearchError"
    assert result.synthesis["status"] == "ready"
    assert writer.calls


def test_required_web_failure_stops_before_claim_extraction_or_writing():
    web = FakeWorker(fail=True)
    mission, extractor, writer = _mission(web=web, documents=None, data=None)

    with pytest.raises(DeepResearchError, match="required research task web-primary failed"):
        asyncio.run(
            mission.run(
                DeepResearchMissionRequest(
                    objective="Required web research",
                    include_documents=False,
                    include_data=False,
                )
            )
        )

    assert extractor.calls == []
    assert writer.calls == []


def test_missing_optional_data_query_is_reported_without_synthesizing_it_as_success():
    web = FakeWorker()
    data = FakeDataWorker()
    mission, _, _ = _mission(web=web, documents=None, data=data)

    result = asyncio.run(
        mission.run(
            DeepResearchMissionRequest(
                objective="Research with optional structured data",
                include_documents=False,
                include_data=True,
            )
        )
    )

    assert result.status == "partial"
    assert result.task_failures[0]["workstream"] == "data"
    assert "no explicit DataQuerySpec" in result.task_failures[0]["message"]
    assert data.calls == []
    assert result.release_readiness["release_ready"] is False


def test_data_queries_cannot_target_tasks_outside_active_plan():
    web = FakeWorker()
    mission, extractor, writer = _mission(web=web, documents=None, data=None)

    with pytest.raises(DeepResearchError, match="outside the active research plan"):
        asyncio.run(
            mission.run(
                DeepResearchMissionRequest(
                    objective="Web only",
                    include_documents=False,
                    include_data=False,
                    data_queries={"invented-task": DataQuerySpec(table="operation_runs")},
                )
            )
        )

    assert web.calls == []
    assert extractor.calls == []
    assert writer.calls == []
