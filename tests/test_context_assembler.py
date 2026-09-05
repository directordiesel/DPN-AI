import pytest

from app.context_assembler import ContextAssembler


class FakeMemory:
    async def recall(self, query, project_id=None, conversation_id=None, limit=12):
        return {
            "ok": True,
            "results": [
                {"namespace": "global", "source": "g", "content": "global fact"},
                {"namespace": "project:p1", "source": "p", "content": "project fact"},
                {"namespace": "conversation:c1", "source": "c", "content": "conversation fact"},
                {"namespace": "project:p2", "source": "leak", "content": "must not leak"},
            ],
        }


class FakeRAG:
    async def retrieve(self, query, project_id=None, knowledge_base=None, limit=10):
        return {
            "ok": True,
            "context": "[S1] docs/a.txt\nsource evidence",
            "citations": [{"ref": "S1", "locator": "docs/a.txt"}],
        }


@pytest.mark.asyncio
async def test_context_assembler_filters_unrelated_scopes_and_keeps_citations():
    assembler = ContextAssembler(max_chars=4000)
    bundle = await assembler.assemble(
        query="question",
        memory_service=FakeMemory(),
        rag_engine=FakeRAG(),
        project_id="p1",
        conversation_id="c1",
    )

    assert "global fact" in bundle.memory_context
    assert "project fact" in bundle.memory_context
    assert "conversation fact" in bundle.memory_context
    assert "must not leak" not in bundle.memory_context
    assert bundle.citations == [{"ref": "S1", "locator": "docs/a.txt"}]
    assert bundle.namespaces == ["global", "project:p1", "conversation:c1"]


@pytest.mark.asyncio
async def test_context_assembler_enforces_total_budget():
    class BigMemory:
        async def recall(self, *args, **kwargs):
            return {"results": [{"namespace": "global", "source": "x", "content": "m" * 6000}]}

    class BigRAG:
        async def retrieve(self, *args, **kwargs):
            return {"context": "r" * 6000, "citations": []}

    assembler = ContextAssembler(max_chars=2000, memory_fraction=0.5)
    bundle = await assembler.assemble(
        query="question",
        memory_service=BigMemory(),
        rag_engine=BigRAG(),
    )

    assert bundle.total_chars <= 2000
    assert len(bundle.memory_context) <= 1000
    assert len(bundle.retrieval_context) <= 1000


def test_context_assembler_rejects_invalid_budget_settings():
    with pytest.raises(ValueError, match="max_chars"):
        ContextAssembler(max_chars=1999)
    with pytest.raises(ValueError, match="memory_fraction"):
        ContextAssembler(memory_fraction=0.05)
