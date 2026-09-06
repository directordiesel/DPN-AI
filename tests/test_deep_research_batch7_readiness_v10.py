import asyncio
from dataclasses import dataclass

from app.deep_research_claim_orchestrator_v10 import DeepResearchClaimOrchestrator
from app.deep_research_engine_v10 import EvidenceNode, ResearchPlan, ResearchTask, ResearchWorkstream
from app.deep_research_mission_v10 import DeepResearchMissionOrchestrator, DeepResearchMissionRequest
from app.deep_research_writer_v10 import DeepResearchWriter
from app.research_intelligence import ResearchSource


@dataclass(frozen=True)
class WorkerResult:
    evidence_count: int


class SelectiveWebWorker:
    async def execute(self, task, graph):
        # Simulate a future multi-task WEB plan where one required task reports a
        # completed worker result with the wrong task identity. Release readiness
        # must be based on exact planned task IDs, not merely the WEB workstream.
        source_id = f"source-{task.task_id}"
        evidence_id = f"evidence-{task.task_id}"
        graph.add_source(
            ResearchSource(
                source_id=source_id,
                title=source_id,
                url=f"https://example.test/{source_id}",
                domain="example.test",
                snippet="evidence",
                content="evidence",
                source_type="web",
                authority_score=0.9,
                freshness_score=0.9,
                relevance_score=0.9,
                quality_score=0.9,
                metadata={},
            )
        )
        graph.add_evidence(
            EvidenceNode(
                evidence_id=evidence_id,
                source_id=source_id,
                source_type="web",
                title=source_id,
                locator=f"https://example.test/{source_id}",
                excerpt="trusted evidence",
                quality_score=0.9,
                freshness_score=0.9,
                metadata={"task_id": task.task_id, "workstream": "web"},
            )
        )
        return {"task_id": "spoofed-task-id", "evidence_count": 1}


class Extractor:
    async def extract_claims(self, objective, evidence):
        return [
            {
                "claim_id": "claim-1",
                "text": "The evidence supports the finding.",
                "supporting_evidence_ids": [item["evidence_id"] for item in evidence],
                "refuting_evidence_ids": [],
                "confidence": 0.9,
            }
        ]


class WriterProvider:
    async def write(self, objective, claims):
        return {
            "sections": [
                {
                    "title": "Finding",
                    "text": "The finding is grounded in admitted evidence.",
                    "claim_ids": ["claim-1"],
                }
            ]
        }


def test_release_readiness_records_exact_completed_task_ids(monkeypatch):
    import app.deep_research_mission_v10 as mission_module

    class TwoWebTaskDirector:
        def __init__(self, **kwargs):
            pass

        def plan(self, objective):
            plan = ResearchPlan(
                objective=objective,
                tasks=(
                    ResearchTask("web-primary", ResearchWorkstream.WEB, objective, "primary", True),
                    ResearchTask("web-secondary", ResearchWorkstream.WEB, objective, "secondary", True),
                ),
            )
            plan.validate()
            return plan

    monkeypatch.setattr(mission_module, "ResearchDirector", TwoWebTaskDirector)
    orchestrator = DeepResearchMissionOrchestrator(
        web_worker=SelectiveWebWorker(),
        document_worker=None,
        data_worker=None,
        claim_orchestrator=DeepResearchClaimOrchestrator(Extractor()),
        writer=DeepResearchWriter(WriterProvider()),
    )

    result = asyncio.run(
        orchestrator.run(
            DeepResearchMissionRequest(
                objective="Audit exact task completion",
                include_documents=False,
                include_data=False,
            )
        )
    )

    assert result.status == "ready"
    assert result.release_readiness["release_ready"] is True
    assert result.release_readiness["required_tasks_complete"] is True
    assert result.release_readiness["completed_task_ids"] == ["web-primary", "web-secondary"]
    assert result.release_readiness["missing_required_task_ids"] == []
