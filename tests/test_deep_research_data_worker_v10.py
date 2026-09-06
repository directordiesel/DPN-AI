from __future__ import annotations

import pytest

from app.deep_research_data_worker_v10 import DataQuerySpec, DeepResearchDataWorker
from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, ResearchTask, ResearchWorkstream


class FakeDataRuntime:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = []

    async def read(self, table, **kwargs):
        self.calls.append((table, kwargs))
        return self.bundle


def task(*, required=True, workstream=ResearchWorkstream.DATA):
    return ResearchTask(
        task_id="data-primary",
        workstream=workstream,
        query="recent operation status",
        purpose="inspect governed operational data",
        required=required,
    )


def bundle(*, table="operation_runs", rows=None, action="read", provenance=None):
    rows = [{"id": 1, "status": "completed"}] if rows is None else rows
    return {
        "ok": True,
        "action": action,
        "result": {"table": table, "row_count": len(rows), "rows": rows},
        "provenance": provenance or {
            "provider": "sqlite",
            "database": "dpn.db",
            "table": table,
            "read_only": True,
            "parameterized": True,
            "limit": 25,
        },
    }


@pytest.mark.asyncio
async def test_data_worker_admits_governed_sql_rows_as_evidence():
    runtime = FakeDataRuntime(bundle(rows=[{"id": 1, "status": "completed"}, {"id": 2, "status": "failed"}]))
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(runtime)
    spec = DataQuerySpec(
        table="operation_runs",
        columns=("id", "status"),
        filters=(("status", "completed"),),
        order_by="id",
        order_direction="DESC",
        limit=25,
    )

    result = await worker.execute(task(), graph, spec)

    assert result.row_count == 2
    assert result.evidence_count == 2
    assert len(graph.sources) == 1
    assert len(graph.evidence) == 2
    assert graph.sources[0].metadata["read_only"] is True
    assert graph.sources[0].metadata["parameterized"] is True
    assert all(item.metadata["workstream"] == "data" for item in graph.evidence)
    assert runtime.calls == [("operation_runs", {
        "columns": ["id", "status"],
        "filters": {"status": "completed"},
        "order_by": "id",
        "order_direction": "DESC",
        "limit": 25,
        "search": False,
    })]


@pytest.mark.asyncio
async def test_data_worker_rejects_wrong_workstream_before_runtime_call():
    runtime = FakeDataRuntime(bundle())
    worker = DeepResearchDataWorker(runtime)

    with pytest.raises(DeepResearchError, match="only accepts structured-data"):
        await worker.execute(task(workstream=ResearchWorkstream.WEB), EvidenceGraph(), DataQuerySpec(table="operation_runs"))

    assert runtime.calls == []


@pytest.mark.asyncio
async def test_data_worker_rejects_non_read_runtime_action_transactionally():
    runtime = FakeDataRuntime(bundle(action="search"))
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(runtime)

    with pytest.raises(DeepResearchError, match="read-only action boundary"):
        await worker.execute(task(), graph, DataQuerySpec(table="operation_runs"))

    assert graph.sources == ()
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_data_worker_requires_read_only_parameterized_provenance():
    provenance = {
        "provider": "sqlite",
        "database": "dpn.db",
        "table": "operation_runs",
        "read_only": False,
        "parameterized": True,
    }
    runtime = FakeDataRuntime(bundle(provenance=provenance))
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(runtime)

    with pytest.raises(DeepResearchError, match="did not prove read-only parameterized"):
        await worker.execute(task(), graph, DataQuerySpec(table="operation_runs"))

    assert graph.sources == ()
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_data_worker_rejects_table_escape_and_provider_mismatch():
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(FakeDataRuntime(bundle(table="audit_events")))
    with pytest.raises(DeepResearchError, match="wrong table"):
        await worker.execute(task(), graph, DataQuerySpec(table="operation_runs"))
    assert graph.sources == ()

    provenance = {
        "provider": "postgres",
        "database": "dpn.db",
        "table": "operation_runs",
        "read_only": True,
        "parameterized": True,
    }
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(FakeDataRuntime(bundle(provenance=provenance)))
    with pytest.raises(DeepResearchError, match="unexpected provider"):
        await worker.execute(task(), graph, DataQuerySpec(table="operation_runs"))
    assert graph.sources == ()


@pytest.mark.asyncio
async def test_data_worker_rejects_row_limit_and_count_mismatch():
    runtime = FakeDataRuntime(bundle(rows=[{"id": 1}, {"id": 2}]))
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(runtime)
    with pytest.raises(DeepResearchError, match="exceeded the requested row limit"):
        await worker.execute(task(), graph, DataQuerySpec(table="operation_runs", limit=1))
    assert graph.evidence == ()

    malformed = bundle(rows=[{"id": 1}])
    malformed["result"]["row_count"] = 2
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(FakeDataRuntime(malformed))
    with pytest.raises(DeepResearchError, match="row count did not match"):
        await worker.execute(task(), graph, DataQuerySpec(table="operation_runs"))
    assert graph.evidence == ()


@pytest.mark.asyncio
async def test_data_worker_required_empty_fails_optional_empty_succeeds_without_source():
    runtime = FakeDataRuntime(bundle(rows=[]))
    worker = DeepResearchDataWorker(runtime)

    with pytest.raises(DeepResearchError, match="required data task"):
        await worker.execute(task(required=True), EvidenceGraph(), DataQuerySpec(table="operation_runs"))

    graph = EvidenceGraph()
    result = await worker.execute(task(required=False), graph, DataQuerySpec(table="operation_runs"))
    assert result.evidence_count == 0
    assert graph.sources == ()


def test_data_query_spec_rejects_unbounded_or_ambiguous_requests():
    with pytest.raises(DeepResearchError, match="table is required"):
        DataQuerySpec(table="").validate()
    with pytest.raises(DeepResearchError, match="between 1 and 100"):
        DataQuerySpec(table="operation_runs", limit=101).validate()
    with pytest.raises(DeepResearchError, match="filter keys must be unique"):
        DataQuerySpec(table="operation_runs", filters=(("status", "a"), ("status", "b"))).validate()
    with pytest.raises(DeepResearchError, match="order direction"):
        DataQuerySpec(table="operation_runs", order_direction="SIDEWAYS").validate()


@pytest.mark.asyncio
async def test_data_worker_bounds_excerpt_and_preflights_graph_collision():
    runtime = FakeDataRuntime(bundle(rows=[{"payload": "x" * 1000}]))
    graph = EvidenceGraph()
    worker = DeepResearchDataWorker(runtime, max_excerpt_chars=256)
    spec = DataQuerySpec(table="operation_runs")

    await worker.execute(task(), graph, spec)
    assert len(graph.evidence[0].excerpt) == 256

    conflicting_source = graph.sources[0]
    graph2 = EvidenceGraph()
    from app.research_intelligence import ResearchSource
    graph2.add_source(ResearchSource(
        source_id=conflicting_source.source_id,
        title="collision",
        url="dpn://collision",
        domain="local.dpn",
    ))
    with pytest.raises(DeepResearchError, match="source id collision"):
        await worker.execute(task(), graph2, spec)
    assert graph2.evidence == ()
