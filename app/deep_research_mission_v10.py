from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping, Protocol

from app.deep_research_claim_orchestrator_v10 import DeepResearchClaimOrchestrator
from app.deep_research_data_worker_v10 import DataQuerySpec
from app.deep_research_engine_v10 import (
    DeepResearchError,
    EvidenceGraph,
    ResearchDirector,
    ResearchTask,
    ResearchWorkstream,
)
from app.deep_research_writer_v10 import DeepResearchWriter


class ResearchWorkerProtocol(Protocol):
    async def execute(self, task: ResearchTask, graph: EvidenceGraph) -> Any: ...


class DataResearchWorkerProtocol(Protocol):
    async def execute(self, task: ResearchTask, graph: EvidenceGraph, spec: DataQuerySpec) -> Any: ...


@dataclass(frozen=True)
class DeepResearchMissionRequest:
    objective: str
    include_web: bool = True
    include_documents: bool = True
    include_data: bool = True
    require_mixed_workstreams: bool = False
    data_queries: Mapping[str, DataQuerySpec] | None = None

    def validate(self) -> None:
        if not " ".join((self.objective or "").split()):
            raise DeepResearchError("research mission objective is required")
        if not (self.include_web or self.include_documents or self.include_data):
            raise DeepResearchError("research mission requires at least one enabled workstream")
        if self.data_queries is not None:
            for task_id, spec in self.data_queries.items():
                if not str(task_id).strip():
                    raise DeepResearchError("data query task ids must be non-empty")
                if not isinstance(spec, DataQuerySpec):
                    raise DeepResearchError("data query mappings must contain DataQuerySpec values")
                spec.validate()


@dataclass(frozen=True)
class DeepResearchMissionResult:
    status: str
    objective: str
    task_results: tuple[dict[str, Any], ...]
    task_failures: tuple[dict[str, Any], ...]
    graph_summary: dict[str, Any]
    claim_assessment: dict[str, Any]
    synthesis: dict[str, Any]
    release_readiness: dict[str, Any]


class DeepResearchMissionOrchestrator:
    """Runs bounded research workstreams through one fail-closed evidence-to-report mission.

    Workers keep their existing trust boundaries. The mission layer coordinates them
    deterministically, tolerates failures only for tasks the ResearchDirector marked
    optional, and never upgrades partial evidence into release-ready synthesis.
    """

    def __init__(
        self,
        *,
        web_worker: ResearchWorkerProtocol | None,
        document_worker: ResearchWorkerProtocol | None,
        data_worker: DataResearchWorkerProtocol | None,
        claim_orchestrator: DeepResearchClaimOrchestrator,
        writer: DeepResearchWriter,
        max_failure_message_chars: int = 500,
    ) -> None:
        if not 64 <= max_failure_message_chars <= 2_000:
            raise ValueError("max_failure_message_chars must be between 64 and 2000")
        self.web_worker = web_worker
        self.document_worker = document_worker
        self.data_worker = data_worker
        self.claim_orchestrator = claim_orchestrator
        self.writer = writer
        self.max_failure_message_chars = max_failure_message_chars

    @staticmethod
    def _result_payload(result: Any) -> dict[str, Any]:
        if is_dataclass(result):
            raw = asdict(result)
        elif isinstance(result, dict):
            raw = dict(result)
        else:
            raise DeepResearchError("research worker returned an unsupported result type")
        return {str(key): value for key, value in raw.items()}

    def _failure_payload(self, task: ResearchTask, exc: Exception) -> dict[str, Any]:
        message = " ".join(str(exc).split())[: self.max_failure_message_chars]
        return {
            "task_id": task.task_id,
            "workstream": task.workstream.value,
            "required": task.required,
            "error_type": type(exc).__name__,
            "message": message or "research task failed without an error message",
        }

    async def _execute_task(
        self,
        task: ResearchTask,
        graph: EvidenceGraph,
        data_queries: Mapping[str, DataQuerySpec],
    ) -> dict[str, Any]:
        if task.workstream == ResearchWorkstream.WEB:
            if self.web_worker is None:
                raise DeepResearchError("web research worker is not configured")
            result = await self.web_worker.execute(task, graph)
        elif task.workstream == ResearchWorkstream.DOCUMENTS:
            if self.document_worker is None:
                raise DeepResearchError("document research worker is not configured")
            result = await self.document_worker.execute(task, graph)
        elif task.workstream == ResearchWorkstream.DATA:
            if self.data_worker is None:
                raise DeepResearchError("structured-data research worker is not configured")
            spec = data_queries.get(task.task_id)
            if spec is None:
                raise DeepResearchError("structured-data research task has no explicit DataQuerySpec")
            result = await self.data_worker.execute(task, graph, spec)
        else:  # pragma: no cover - enum exhaustiveness guard
            raise DeepResearchError("unsupported research workstream")

        payload = self._result_payload(result)
        payload["task_id"] = task.task_id
        payload["workstream"] = task.workstream.value
        payload["required"] = task.required
        payload["status"] = "completed"
        return payload

    async def run(self, request: DeepResearchMissionRequest) -> DeepResearchMissionResult:
        request.validate()
        objective = " ".join(request.objective.split())
        director = ResearchDirector(
            include_web=request.include_web,
            include_documents=request.include_documents,
            include_data=request.include_data,
        )
        plan = director.plan(objective)
        graph = EvidenceGraph()
        data_queries = dict(request.data_queries or {})

        known_task_ids = {task.task_id for task in plan.tasks}
        unexpected_specs = sorted(set(data_queries) - known_task_ids)
        if unexpected_specs:
            raise DeepResearchError(
                "data query mappings reference tasks outside the active research plan: " + ", ".join(unexpected_specs)
            )

        task_results: list[dict[str, Any]] = []
        task_failures: list[dict[str, Any]] = []
        for task in plan.tasks:
            try:
                task_results.append(await self._execute_task(task, graph, data_queries))
            except Exception as exc:
                failure = self._failure_payload(task, exc)
                if task.required:
                    raise DeepResearchError(
                        f"required research task {task.task_id} failed: {failure['message']}"
                    ) from exc
                task_failures.append(failure)

        if not graph.evidence:
            raise DeepResearchError("research mission produced no admissible evidence")

        assessment = await self.claim_orchestrator.extract_and_assess(
            objective,
            graph,
            require_mixed_workstreams=request.require_mixed_workstreams,
        )
        write_result = await self.writer.synthesize(objective, graph)

        graph_summary = {
            "source_count": len(graph.sources),
            "evidence_count": len(graph.evidence),
            "claim_count": len(graph.claims),
            "workstreams_with_evidence": sorted(
                {
                    str(node.metadata.get("workstream") or "").strip()
                    for node in graph.evidence
                    if str(node.metadata.get("workstream") or "").strip()
                }
            ),
        }
        claim_payload = {
            "claim_count": assessment.claim_count,
            "workstreams_used": list(assessment.workstreams_used),
            "fact_checks": [dict(item) for item in assessment.fact_checks],
            "conflicts": [dict(item) for item in assessment.conflicts],
            "citation_validation": dict(assessment.citation_validation),
            "readiness": dict(assessment.readiness),
        }
        synthesis_payload = {
            "status": write_result.status,
            "report": write_result.report,
            "sections": [dict(item) for item in write_result.sections],
            "citation_count": write_result.citation_count,
            "unresolved_conflicts": [dict(item) for item in write_result.unresolved_conflicts],
            "blocked_claims": [dict(item) for item in write_result.blocked_claims],
        }

        completed_workstreams = {item["workstream"] for item in task_results}
        failed_workstreams = {item["workstream"] for item in task_failures}
        required_tasks_complete = all(
            task.workstream.value in completed_workstreams for task in plan.tasks if task.required
        )
        release_ready = (
            required_tasks_complete
            and not failed_workstreams
            and bool(assessment.readiness.get("ready"))
            and bool(assessment.citation_validation.get("ok"))
            and write_result.status == "ready"
        )
        readiness = {
            "release_ready": release_ready,
            "required_tasks_complete": required_tasks_complete,
            "optional_failure_count": len(task_failures),
            "claim_readiness": bool(assessment.readiness.get("ready")),
            "citation_validation_ok": bool(assessment.citation_validation.get("ok")),
            "synthesis_ready": write_result.status == "ready",
            "completed_workstreams": sorted(completed_workstreams),
            "failed_workstreams": sorted(failed_workstreams),
        }
        status = "ready" if release_ready else ("blocked" if write_result.status == "blocked" else "partial")

        return DeepResearchMissionResult(
            status=status,
            objective=objective,
            task_results=tuple(task_results),
            task_failures=tuple(task_failures),
            graph_summary=graph_summary,
            claim_assessment=claim_payload,
            synthesis=synthesis_payload,
            release_readiness=readiness,
        )


__all__ = [
    "DataResearchWorkerProtocol",
    "DeepResearchMissionOrchestrator",
    "DeepResearchMissionRequest",
    "DeepResearchMissionResult",
    "ResearchWorkerProtocol",
]
