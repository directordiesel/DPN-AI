import asyncio

import pytest

from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, ResearchTask, ResearchWorkstream
from app.deep_research_web_worker_v10 import DeepResearchWebWorker
from app.research_intelligence import ResearchSource


class FakeRuntime:
    def __init__(self, payload):
        self.payload = payload
        self.queries = []

    async def research(self, query):
        self.queries.append(query)
        return self.payload


def source(source_id="src-1", *, content="verified source content", quality=0.9, freshness=0.8):
    return {
        "source_id": source_id,
        "title": "Primary source",
        "url": f"https://example.com/{source_id}",
        "domain": "example.com",
        "snippet": "source snippet",
        "content": content,
        "published_at": "2026-09-06T12:00:00+00:00",
        "source_type": "web",
        "authority_score": 0.8,
        "freshness_score": freshness,
        "relevance_score": 0.95,
        "quality_score": quality,
        "metadata": {"provider": "test"},
    }


def web_task(required=True):
    return ResearchTask(
        task_id="web-primary",
        workstream=ResearchWorkstream.WEB,
        query="DPN AI v10 research",
        purpose="collect independent evidence",
        required=required,
    )


def test_worker_admits_runtime_sources_with_provenance():
    runtime = FakeRuntime({"ok": True, "sources": [source()], "partial": False, "fetch_failures": []})
    graph = EvidenceGraph()
    result = asyncio.run(DeepResearchWebWorker(runtime).execute(web_task(), graph))

    assert runtime.queries == ["DPN AI v10 research"]
    assert result.source_count == 1
    assert result.evidence_count == 1
    assert len(graph.sources) == 1
    assert len(graph.evidence) == 1
    evidence = graph.evidence[0]
    assert evidence.source_id == "src-1"
    assert evidence.locator == "https://example.com/src-1"
    assert evidence.metadata["task_id"] == "web-primary"
    assert evidence.metadata["workstream"] == "web"


def test_worker_bounds_source_count_and_excerpt_size():
    payload = {"ok": True, "sources": [source("a", content="x" * 1000), source("b")], "partial": False}
    graph = EvidenceGraph()
    worker = DeepResearchWebWorker(FakeRuntime(payload), max_sources=1, max_excerpt_chars=256)
    result = asyncio.run(worker.execute(web_task(), graph))

    assert result.source_count == 1
    assert len(graph.evidence[0].excerpt) == 256


def test_worker_fails_closed_without_mutating_graph_on_invalid_source():
    payload = {"ok": True, "sources": [source("good"), {**source("bad"), "url": ""}]}
    graph = EvidenceGraph()

    with pytest.raises(DeepResearchError, match="required provenance"):
        asyncio.run(DeepResearchWebWorker(FakeRuntime(payload)).execute(web_task(), graph))

    assert graph.sources == ()
    assert graph.evidence == ()


def test_worker_rejects_duplicate_source_ids_before_commit():
    payload = {"ok": True, "sources": [source("dup"), source("dup", content="other")]}
    graph = EvidenceGraph()

    with pytest.raises(DeepResearchError, match="duplicate web source id"):
        asyncio.run(DeepResearchWebWorker(FakeRuntime(payload)).execute(web_task(), graph))

    assert graph.sources == ()


def test_worker_preflights_live_graph_collisions_before_any_commit():
    graph = EvidenceGraph()
    graph.add_source(ResearchSource(
        source_id="collision",
        title="Existing",
        url="https://existing.example/source",
        domain="existing.example",
    ))
    before = graph.to_dict()
    payload = {"ok": True, "sources": [source("new-source"), source("collision")]}

    with pytest.raises(DeepResearchError, match="collision detected before graph commit"):
        asyncio.run(DeepResearchWebWorker(FakeRuntime(payload)).execute(web_task(), graph))

    assert graph.to_dict() == before


def test_required_task_rejects_empty_admissible_evidence():
    payload = {"ok": True, "sources": [source(content="") | {"snippet": ""}]}

    with pytest.raises(DeepResearchError, match="no admissible evidence"):
        asyncio.run(DeepResearchWebWorker(FakeRuntime(payload)).execute(web_task(required=True), EvidenceGraph()))


def test_optional_task_may_return_empty_without_claiming_evidence():
    payload = {"ok": True, "sources": []}
    result = asyncio.run(DeepResearchWebWorker(FakeRuntime(payload)).execute(web_task(required=False), EvidenceGraph()))
    assert result.source_count == 0
    assert result.evidence_count == 0


def test_worker_rejects_failed_runtime_and_wrong_workstream():
    failed = FakeRuntime({"ok": False, "error": "network unavailable", "sources": []})
    with pytest.raises(DeepResearchError, match="trusted evidence"):
        asyncio.run(DeepResearchWebWorker(failed).execute(web_task(), EvidenceGraph()))

    task = ResearchTask("documents-primary", ResearchWorkstream.DOCUMENTS, "q", "p", False)
    with pytest.raises(DeepResearchError, match="only accepts web"):
        asyncio.run(DeepResearchWebWorker(FakeRuntime({"ok": True, "sources": []})).execute(task, EvidenceGraph()))


def test_worker_reports_partial_fetch_failures_without_exposing_failure_body():
    payload = {
        "ok": True,
        "sources": [source()],
        "partial": True,
        "fetch_failures": [{"url": "https://failed.example", "error": "provider detail"}],
    }
    result = asyncio.run(DeepResearchWebWorker(FakeRuntime(payload)).execute(web_task(), EvidenceGraph()))
    assert result.partial is True
    assert result.fetch_failure_count == 1
    assert not hasattr(result, "fetch_failures")
