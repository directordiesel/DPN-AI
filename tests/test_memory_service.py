import asyncio

from app.memory_service import MemoryService


class FakeDB:
    def __init__(self):
        self.memories = {}

    def upsert_memory(self, key, value):
        self.memories[key] = value

    def delete_memory(self, key):
        return self.memories.pop(key, None) is not None


class FakeSemantic:
    def __init__(self, add_ok=True):
        self.add_ok = add_ok
        self.add_calls = []
        self.search_calls = []

    async def add(self, content, namespace="global", source="manual", metadata=None, item_id=None):
        self.add_calls.append({
            "content": content,
            "namespace": namespace,
            "source": source,
            "metadata": metadata,
            "item_id": item_id,
        })
        if not self.add_ok:
            return {"ok": False, "error": "embedding unavailable"}
        return {"ok": True, "dimensions": 3}

    async def search_many(self, query, namespaces, limit=8):
        self.search_calls.append((query, list(namespaces), limit))
        return {
            "ok": True,
            "model": "fake-embed",
            "results": [{"id": "m1", "namespace": list(namespaces)[0], "content": "result", "score": 0.9}],
        }


def test_project_memory_persists_with_stable_scoped_identity():
    db = FakeDB()
    semantic = FakeSemantic()
    service = MemoryService(db, semantic)

    first = asyncio.run(service.remember("Preferred Model", "alpha", scope="project", project_id="p1"))
    second = asyncio.run(service.remember("Preferred Model", "beta", scope="project", project_id="p1"))

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["memory"]["memory_id"] == second["memory"]["memory_id"]
    assert db.memories["v9:project:p1:preferred model"] == "beta"
    assert semantic.add_calls[-1]["namespace"] == "project:p1"
    assert semantic.add_calls[-1]["item_id"] == first["memory"]["memory_id"]


def test_partial_semantic_failure_rolls_back_key_value_memory():
    db = FakeDB()
    service = MemoryService(db, FakeSemantic(add_ok=False))

    result = asyncio.run(service.remember("key", "value"))

    assert result["ok"] is False
    assert db.memories == {}


def test_recall_only_searches_visible_scopes():
    semantic = FakeSemantic()
    service = MemoryService(FakeDB(), semantic)

    result = asyncio.run(service.recall("model", project_id="p1", conversation_id="c1", limit=6))

    assert result["ok"] is True
    assert semantic.search_calls == [(
        "model",
        ["global", "project:p1", "conversation:c1"],
        6,
    )]


def test_unrelated_project_namespace_is_never_in_recall_scope():
    semantic = FakeSemantic()
    service = MemoryService(FakeDB(), semantic)

    asyncio.run(service.recall("secret", project_id="p1"))

    _, namespaces, _ = semantic.search_calls[0]
    assert "project:p1" in namespaces
    assert "project:p2" not in namespaces
