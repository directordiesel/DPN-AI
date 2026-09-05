import asyncio

from app.rag_engine import RAGEngine


async def semantic_search(query: str, namespace: str, limit: int):
    return {
        "ok": True,
        "results": [
            {"id": "m1", "source": "memory:policy", "content": "DPN AI uses explicit project-scoped memory.", "score": 0.92, "metadata": {"kind": "memory"}},
            {"id": "m2", "source": "memory:dup", "content": "Shared retrieval evidence", "score": 0.80},
        ][:limit],
    }


def keyword_search(query: str, limit: int):
    return {
        "ok": True,
        "results": [
            {"path": "docs/architecture.md", "content": "Shared retrieval evidence", "score": -3.0},
            {"path": "docs/rag.md", "content": "RAG responses must preserve source attribution.", "score": -2.0},
        ][:limit],
    }


def test_namespace_isolates_project_and_knowledge_base():
    assert RAGEngine.namespace_for() == "global"
    assert RAGEngine.namespace_for(project_id="p1") == "project:p1"
    assert RAGEngine.namespace_for(knowledge_base="ops") == "kb:ops"
    assert RAGEngine.namespace_for(project_id="p1", knowledge_base="ops") == "project:p1:kb:ops"


def test_hybrid_retrieval_deduplicates_and_attributes_sources():
    engine = RAGEngine(semantic_search, keyword_search, max_context_chars=5000, per_source_chars=1200)
    result = asyncio.run(engine.retrieve("memory architecture", project_id="p1", knowledge_base="ops", limit=10))

    assert result["ok"] is True
    assert result["namespace"] == "project:p1:kb:ops"
    assert result["deduplicated_count"] == 3
    assert len(result["sources"]) == 3
    hybrid = next(item for item in result["sources"] if item["content"] == "Shared retrieval evidence")
    assert hybrid["source_type"] == "hybrid"
    assert hybrid["semantic_score"] > 0
    assert hybrid["keyword_score"] > 0
    assert result["citations"][0]["ref"] == "S1"
    assert "[S1]" in result["context"]


def test_context_budget_is_enforced():
    async def semantic(query: str, namespace: str, limit: int):
        return {"results": [{"id": "1", "source": "large", "content": "x" * 4000, "score": 1.0}]}

    engine = RAGEngine(semantic, lambda query, limit: {"results": []}, max_context_chars=1000, per_source_chars=800)
    result = asyncio.run(engine.retrieve("large"))

    assert len(result["context"]) <= 1000
    assert result["context_chars"] <= 1000


def test_empty_query_fails_closed():
    engine = RAGEngine(semantic_search, keyword_search)
    result = asyncio.run(engine.retrieve("   "))

    assert result["ok"] is False
    assert result["sources"] == []
