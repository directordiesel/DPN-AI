from __future__ import annotations

import pytest

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    KnowledgeClass,
    MemoryContext,
    MemoryLayer,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.memory_scope import MemoryScope, ScopedMemory
from app.memory_service import MemoryService


class FakeDB:
    def __init__(self):
        self.memories: dict[str, str] = {}
        self.semantic_items: list[dict] = []
        self.fail_list = False

    def upsert_memory(self, key, value):
        self.memories[key] = value

    def delete_memory(self, key):
        self.memories.pop(key, None)

    def list_semantic_items(self, namespace, limit=5000):
        if self.fail_list:
            raise RuntimeError("db unavailable")
        return [item for item in self.semantic_items if item["namespace"] == namespace][:limit]


class FakeSemantic:
    def __init__(self, db: FakeDB):
        self.db = db

    async def add(self, content, namespace="global", source="manual", metadata=None, item_id=None):
        item = {
            "id": item_id,
            "namespace": namespace,
            "source": source,
            "content": content,
            "metadata": dict(metadata or {}),
            "vector": [1.0, 0.0],
        }
        self.db.semantic_items = [entry for entry in self.db.semantic_items if entry["id"] != item_id]
        self.db.semantic_items.append(item)
        return {"ok": True, "item": {k: v for k, v in item.items() if k != "vector"}, "dimensions": 2}

    async def search_many(self, query, namespaces, limit=8):
        tokens = {token.lower() for token in query.split()}
        results = []
        for item in self.db.semantic_items:
            if item["namespace"] not in namespaces:
                continue
            words = {token.lower() for token in item["content"].split()}
            overlap = len(tokens.intersection(words)) / max(1, len(tokens))
            result = {k: v for k, v in item.items() if k != "vector"}
            result["score"] = max(0.25, overlap)
            results.append(result)
        results.sort(key=lambda item: (-item["score"], item["namespace"], item["id"]))
        return {"ok": True, "model": "fake", "namespaces": list(namespaces), "results": results[:limit]}


@pytest.fixture
def runtime():
    db = FakeDB()
    semantic = FakeSemantic(db)
    service = MemoryService(db, semantic)
    clock = [1_000.0]
    engine = AdvancedLayeredMemory(service, clock=lambda: clock[0], max_working_items=2)
    return engine, db, clock


def provenance(*, evidence=(), confidence=0.9, authority=0.8):
    return MemoryProvenance(
        source_type="test",
        source_id="source-1",
        evidence_ids=tuple(evidence),
        confidence=confidence,
        authority=authority,
    )


def test_scope_model_adds_organization_and_user_without_changing_existing_visibility_order():
    assert ScopedMemory.scope_id(MemoryScope.ORGANIZATION, organization_id="dpn") == "organization:dpn"
    assert ScopedMemory.scope_id(MemoryScope.USER, user_id="diesel") == "user:diesel"
    assert ScopedMemory.visible_namespaces(
        organization_id="dpn", user_id="diesel", project_id="ai", conversation_id="c1"
    ) == ["global", "organization:dpn", "user:diesel", "project:ai", "conversation:c1"]

    with pytest.raises(ValueError, match="organization_id"):
        ScopedMemory.scope_id(MemoryScope.ORGANIZATION)
    with pytest.raises(ValueError, match="user_id"):
        ScopedMemory.scope_id(MemoryScope.USER)


@pytest.mark.asyncio
async def test_project_fact_delegates_to_existing_memory_service_with_typed_provenance(runtime):
    engine, db, _clock = runtime
    result = await engine.remember(
        MemoryWriteRequest(
            layer=MemoryLayer.PROJECT,
            key="release_target",
            content="DPN AI remains a v10 program",
            knowledge_class=KnowledgeClass.FACT,
            provenance=provenance(),
            context=MemoryContext(project_id="dpn-ai"),
        )
    )

    assert result["ok"] is True
    assert result["persistent"] is True
    assert result["scope_id"] == "project:dpn-ai"
    assert result["conflict"] is False
    assert len(db.semantic_items) == 1
    metadata = db.semantic_items[0]["metadata"]
    assert metadata["v10_memory_schema"] == 1
    assert metadata["v10_layer"] == "project"
    assert metadata["v10_logical_key"] == "release_target"
    assert metadata["v10_provenance"]["source_id"] == "source-1"


@pytest.mark.asyncio
async def test_conflicting_versions_are_preserved_and_recall_reports_conflict(runtime):
    engine, db, _clock = runtime
    context = MemoryContext(project_id="p1")
    first = await engine.remember(
        MemoryWriteRequest(
            layer="project",
            key="deployment_region",
            content="Detroit",
            knowledge_class="fact",
            provenance=provenance(),
            context=context,
        )
    )
    second = await engine.remember(
        MemoryWriteRequest(
            layer="project",
            key="deployment_region",
            content="Chicago",
            knowledge_class="fact",
            provenance=provenance(),
            context=context,
        )
    )

    assert first["conflict"] is False
    assert second["conflict"] is True
    assert second["conflicting_memory_ids"] == [first["memory_id"]]
    assert len(db.semantic_items) == 2

    recalled = await engine.recall("deployment region", context=context, layers=["project"], limit=10)
    assert recalled["ok"] is True
    assert recalled["has_conflicts"] is True
    assert len(recalled["conflict_groups"]) == 1
    assert set(recalled["conflict_groups"][0]["memory_ids"]) == {first["memory_id"], second["memory_id"]}
    assert all(item["conflict"] is True for item in recalled["results"])


@pytest.mark.asyncio
async def test_derived_and_inference_memory_require_evidence_before_any_write(runtime):
    engine, db, _clock = runtime
    for knowledge_class in ("derived", "inference"):
        result = await engine.remember(
            MemoryWriteRequest(
                layer="semantic",
                key=f"{knowledge_class}_claim",
                content="Model-generated conclusion",
                knowledge_class=knowledge_class,
                provenance=provenance(evidence=()),
                context=MemoryContext(project_id="p1"),
            )
        )
        assert result["ok"] is False
        assert "requires evidence ids" in result["error"]
    assert db.memories == {}
    assert db.semantic_items == []


@pytest.mark.asyncio
async def test_sensitive_persistent_write_fails_closed_without_external_approval_guard(runtime):
    engine, db, _clock = runtime
    request = MemoryWriteRequest(
        layer="user",
        key="private_preference",
        content="sensitive value",
        knowledge_class="fact",
        provenance=provenance(),
        context=MemoryContext(user_id="u1"),
        sensitive=True,
    )
    denied = await engine.remember(request)
    assert denied == {
        "ok": False,
        "error": "sensitive persistent memory requires approval",
        "stored": False,
    }
    assert db.semantic_items == []

    guarded = AdvancedLayeredMemory(engine.memory_service, approval_guard=lambda req: req.key == "private_preference")
    accepted = await guarded.remember(request)
    assert accepted["ok"] is True
    assert accepted["scope_id"] == "user:u1"


@pytest.mark.asyncio
async def test_working_memory_is_bounded_expiring_and_scope_isolated(runtime):
    engine, _db, clock = runtime
    u1 = MemoryContext(user_id="u1", conversation_id="c1")
    u2 = MemoryContext(user_id="u2", conversation_id="c2")

    for key in ("one", "two", "three"):
        result = await engine.remember(
            MemoryWriteRequest(
                layer="working",
                key=key,
                content=f"working {key}",
                knowledge_class="observation",
                provenance=provenance(),
                context=u1,
                ttl_seconds=10,
            )
        )
        assert result["ok"] is True
        clock[0] += 1

    snapshot = engine.working_snapshot(context=u1)
    assert snapshot["count"] == 2
    assert [item["logical_key"] for item in snapshot["items"]] == ["two", "three"]
    assert engine.working_snapshot(context=u2)["count"] == 0

    clock[0] = 2_000.0
    assert engine.working_snapshot(context=u1)["count"] == 0


@pytest.mark.asyncio
async def test_user_recall_cannot_see_another_user_namespace(runtime):
    engine, _db, _clock = runtime
    for user_id, value in (("u1", "alpha preference"), ("u2", "beta preference")):
        result = await engine.remember(
            MemoryWriteRequest(
                layer="user",
                key="preference",
                content=value,
                knowledge_class="fact",
                provenance=provenance(),
                context=MemoryContext(user_id=user_id),
            )
        )
        assert result["ok"] is True

    recalled = await engine.recall("preference", context=MemoryContext(user_id="u1"), layers=["user"], limit=10)
    assert recalled["ok"] is True
    assert recalled["namespaces"] == ["global", "user:u1"]
    assert [item["content"] for item in recalled["results"]] == ["alpha preference"]


@pytest.mark.asyncio
async def test_layer_scope_mismatch_rejects_before_storage(runtime):
    engine, db, _clock = runtime
    result = await engine.remember(
        MemoryWriteRequest(
            layer="organization",
            scope="project",
            key="policy",
            content="organization policy",
            knowledge_class="fact",
            provenance=provenance(),
            context=MemoryContext(organization_id="dpn", project_id="p1"),
        )
    )
    assert result["ok"] is False
    assert "organization layer requires organization scope" in result["error"]
    assert db.semantic_items == []


@pytest.mark.asyncio
async def test_semantic_default_does_not_promote_conversation_scope_into_long_term_semantic_memory(runtime):
    engine, _db, _clock = runtime
    result = await engine.remember(
        MemoryWriteRequest(
            layer="semantic",
            key="architecture_fact",
            content="Connector writes require governance",
            knowledge_class="derived",
            provenance=provenance(evidence=("e1",)),
            context=MemoryContext(project_id="p1", conversation_id="c1"),
        )
    )
    assert result["ok"] is True
    assert result["scope_id"] == "project:p1"


@pytest.mark.asyncio
async def test_existing_version_verification_failure_blocks_persistent_mutation(runtime):
    engine, db, _clock = runtime
    db.fail_list = True
    result = await engine.remember(
        MemoryWriteRequest(
            layer="project",
            key="blocked",
            content="must not persist",
            knowledge_class="fact",
            provenance=provenance(),
            context=MemoryContext(project_id="p1"),
        )
    )
    assert result == {
        "ok": False,
        "error": "existing memory versions could not be verified",
        "stored": False,
    }
    assert db.memories == {}
    assert db.semantic_items == []
