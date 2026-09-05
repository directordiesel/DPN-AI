import pytest

from app.agent_context_runtime import AgentContextRuntime


class DummySemantic:
    async def search(self, query, namespace="global", limit=8):
        return {
            "ok": True,
            "results": [
                {
                    "id": f"{namespace}-1",
                    "namespace": namespace,
                    "source": "memory",
                    "content": f"memory for {namespace}",
                    "score": 0.9,
                    "metadata": {},
                }
            ],
        }

    async def search_many(self, query, namespaces, limit=8):
        return {
            "ok": True,
            "model": "dummy",
            "results": [
                {
                    "id": f"{namespace}-1",
                    "namespace": namespace,
                    "source": "memory",
                    "content": f"memory for {namespace}",
                    "score": 0.9,
                    "metadata": {},
                }
                for namespace in namespaces
            ],
        }


class DummyKnowledge:
    def search(self, query, limit=8):
        return {
            "ok": True,
            "results": [
                {"path": "docs/guide.md", "content": "workspace evidence", "score": -1.0}
            ],
        }


class DummyDB:
    pass


@pytest.mark.asyncio
async def test_runtime_builds_scoped_context_bundle():
    runtime = AgentContextRuntime(db=DummyDB(), semantic=DummySemantic(), knowledge=DummyKnowledge(), max_chars=4000)
    bundle = await runtime.build("guide", project_id="p1", conversation_id="c1")

    assert bundle.namespaces == ["global", "project:p1", "conversation:c1"]
    assert "memory for global" in bundle.memory_context
    assert "memory for project:p1" in bundle.memory_context
    assert "memory for conversation:c1" in bundle.memory_context
    assert "workspace evidence" in bundle.retrieval_context
    assert bundle.citations
    assert bundle.total_chars <= 4000


@pytest.mark.asyncio
async def test_runtime_excludes_unrelated_scope_memory():
    runtime = AgentContextRuntime(db=DummyDB(), semantic=DummySemantic(), knowledge=DummyKnowledge(), max_chars=4000)
    bundle = await runtime.build("guide", project_id="p1")

    assert "project:p1" in bundle.memory_context
    assert "conversation:c1" not in bundle.memory_context
    assert bundle.namespaces == ["global", "project:p1"]
