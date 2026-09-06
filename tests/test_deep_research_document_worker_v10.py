from __future__ import annotations

import pytest

from app.deep_research_document_worker_v10 import DeepResearchDocumentWorker
from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, ResearchTask, ResearchWorkstream


class FakeDocumentRuntime:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = []

    async def retrieve(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return self.bundle


def task(*, required=True, workstream=ResearchWorkstream.DOCUMENTS):
    return ResearchTask(
        task_id="documents-primary",
        workstream=workstream,
        query="connector readiness evidence",
        purpose="inspect project documents",
        required=required,
    )


def source(source_id="doc-1", namespace="project:alpha", locator="docs/report.md", content="Trusted project evidence."):
    return {
        "source_id": source_id,
        "source_type": "workspace",
        "namespace": namespace,
        "locator": locator,
        "content": content,
        "rerank_score": 0.82,
        "metadata": {"title": "Project report", "freshness_score": 0.75},
    }


@pytest.mark.asyncio
async def test_document_worker_admits_scoped_rag_evidence():
    runtime = FakeDocumentRuntime({
        "ok": True,
        "namespace": "project:alpha",
        "sources": [source()],
        "context_chars": 123,
    })
    graph = EvidenceGraph()
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    result = await worker.execute(task(), graph)

    assert result.namespace == "project:alpha"
    assert result.source_count == 1
    assert result.evidence_count == 1
    assert result.context_chars == 123
    assert len(graph.sources) == 1
    assert len(graph.evidence) == 1
    admitted_source = graph.sources[0]
    admitted_evidence = graph.evidence[0]
    assert admitted_source.metadata["local_retrieval"] is True
    assert admitted_source.metadata["namespace"] == "project:alpha"
    assert admitted_evidence.locator == "docs/report.md"
    assert admitted_evidence.metadata["workstream"] == "documents"
    assert runtime.calls[0][1]["project_id"] == "alpha"


@pytest.mark.asyncio
async def test_document_worker_enforces_project_and_knowledge_base_namespace():
    runtime = FakeDocumentRuntime({"ok": True, "namespace": "project:alpha:kb:runbooks", "sources": []})
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha", knowledge_base="runbooks")

    result = await worker.execute(task(required=False), EvidenceGraph())

    assert result.namespace == "project:alpha:kb:runbooks"
    assert runtime.calls[0][1]["knowledge_base"] == "runbooks"


@pytest.mark.asyncio
async def test_document_worker_rejects_runtime_namespace_escape_before_commit():
    runtime = FakeDocumentRuntime({
        "ok": True,
        "namespace": "global",
        "sources": [source(namespace="global")],
    })
    graph = EvidenceGraph()
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    with pytest.raises(DeepResearchError, match="wrong namespace"):
        await worker.execute(task(), graph)

    assert graph.sources == ()
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_document_worker_rejects_source_namespace_escape_transactionally():
    runtime = FakeDocumentRuntime({
        "ok": True,
        "namespace": "project:alpha",
        "sources": [source("good"), source("bad", namespace="project:other")],
    })
    graph = EvidenceGraph()
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    with pytest.raises(DeepResearchError, match="escaped"):
        await worker.execute(task(), graph)

    assert graph.sources == ()
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_document_worker_rejects_duplicate_source_ids_transactionally():
    runtime = FakeDocumentRuntime({
        "ok": True,
        "namespace": "project:alpha",
        "sources": [source("same"), source("same", locator="docs/other.md")],
    })
    graph = EvidenceGraph()
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    with pytest.raises(DeepResearchError, match="duplicate document source"):
        await worker.execute(task(), graph)

    assert graph.sources == ()
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_document_worker_rejects_missing_provenance_without_partial_commit():
    malformed = source("bad")
    malformed["locator"] = ""
    runtime = FakeDocumentRuntime({
        "ok": True,
        "namespace": "project:alpha",
        "sources": [source("good"), malformed],
    })
    graph = EvidenceGraph()
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    with pytest.raises(DeepResearchError, match="missing required provenance"):
        await worker.execute(task(), graph)

    assert graph.sources == ()
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_document_worker_required_empty_fails_optional_empty_succeeds():
    runtime = FakeDocumentRuntime({"ok": True, "namespace": "project:alpha", "sources": []})
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    with pytest.raises(DeepResearchError, match="required document task"):
        await worker.execute(task(required=True), EvidenceGraph())

    result = await worker.execute(task(required=False), EvidenceGraph())
    assert result.evidence_count == 0


@pytest.mark.asyncio
async def test_document_worker_rejects_wrong_workstream_without_runtime_call():
    runtime = FakeDocumentRuntime({"ok": True, "namespace": "project:alpha", "sources": []})
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha")

    with pytest.raises(DeepResearchError, match="only accepts document"):
        await worker.execute(task(workstream=ResearchWorkstream.WEB), EvidenceGraph())

    assert runtime.calls == []


@pytest.mark.asyncio
async def test_document_worker_bounds_source_count_and_excerpt_size():
    sources = [source(f"doc-{index}", content="x" * 1000) for index in range(5)]
    runtime = FakeDocumentRuntime({"ok": True, "namespace": "project:alpha", "sources": sources})
    graph = EvidenceGraph()
    worker = DeepResearchDocumentWorker(runtime, project_id="alpha", max_sources=2, max_excerpt_chars=256)

    result = await worker.execute(task(), graph)

    assert result.source_count == 2
    assert all(len(item.excerpt) == 256 for item in graph.evidence)
    assert runtime.calls[0][1]["limit"] == 2
