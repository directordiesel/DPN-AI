from __future__ import annotations

import pytest

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    MemoryContext,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.memory_lineage_v10 import MemoryLineageService, MemorySupersessionRequest
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
        results = []
        for item in self.db.semantic_items:
            if item["namespace"] in namespaces:
                result = {k: v for k, v in item.items() if k != "vector"}
                result["score"] = 1.0
                results.append(result)
        return {"ok": True, "model": "fake", "namespaces": list(namespaces), "results": results[:limit]}


@pytest.fixture
def runtime():
    db = FakeDB()
    memory = AdvancedLayeredMemory(MemoryService(db, FakeSemantic(db)))
    return memory, db, MemoryLineageService(memory)


def provenance(*, evidence=(), authority=0.8):
    return MemoryProvenance(
        source_type="verified_test",
        source_id="source-1",
        evidence_ids=tuple(evidence),
        confidence=0.95,
        authority=authority,
    )


async def seed(memory, *, content="Detroit", authority=0.7):
    return await memory.remember(
        MemoryWriteRequest(
            layer="project",
            key="deployment_region",
            content=content,
            knowledge_class="fact",
            provenance=provenance(authority=authority),
            context=MemoryContext(project_id="p1"),
        )
    )


def replacement(*, content="Chicago", evidence=("e-2",), authority=0.9, sensitive=False):
    return MemoryWriteRequest(
        layer="project",
        key="deployment_region",
        content=content,
        knowledge_class="fact",
        provenance=provenance(evidence=evidence, authority=authority),
        context=MemoryContext(project_id="p1"),
        sensitive=sensitive,
    )


@pytest.mark.asyncio
async def test_supersession_preserves_old_version_and_writes_immutable_lineage_receipt(runtime):
    memory, db, lineage = runtime
    old = await seed(memory)

    result = await lineage.supersede(
        MemorySupersessionRequest(
            replacement=replacement(),
            supersedes_memory_ids=(old["memory_id"],),
            reason="new verified deployment evidence",
        )
    )

    assert result["ok"] is True
    assert result["destructive_mutation"] is False
    assert result["conflict_preserved"] is True
    assert result["superseded_memory_ids"] == [old["memory_id"]]
    ids = {item["id"] for item in db.semantic_items}
    assert old["memory_id"] in ids
    assert result["replacement_memory_id"] in ids
    assert result["lineage_receipt_memory_id"] in ids

    receipt = next(item for item in db.semantic_items if item["id"] == result["lineage_receipt_memory_id"])
    assert receipt["metadata"]["v10_layer"] == "procedural"
    assert receipt["metadata"]["v10_knowledge_class"] == "derived"
    assert receipt["metadata"]["v10_provenance"]["source_type"] == "memory_supersession"
    assert old["memory_id"] in receipt["metadata"]["v10_provenance"]["evidence_ids"]
    assert result["replacement_memory_id"] in receipt["metadata"]["v10_provenance"]["evidence_ids"]


@pytest.mark.asyncio
async def test_supersession_requires_evidence_before_any_replacement_write(runtime):
    memory, db, lineage = runtime
    old = await seed(memory)
    before = list(db.semantic_items)

    result = await lineage.supersede(
        MemorySupersessionRequest(
            replacement=replacement(evidence=()),
            supersedes_memory_ids=(old["memory_id"],),
            reason="unsupported change",
        )
    )

    assert result["ok"] is False
    assert "requires evidence ids" in result["error"]
    assert db.semantic_items == before


@pytest.mark.asyncio
async def test_supersession_rejects_target_outside_exact_scope_layer_and_logical_key(runtime):
    memory, db, lineage = runtime
    other = await memory.remember(
        MemoryWriteRequest(
            layer="project",
            key="other_key",
            content="Detroit",
            knowledge_class="fact",
            provenance=provenance(),
            context=MemoryContext(project_id="p1"),
        )
    )
    before = list(db.semantic_items)

    result = await lineage.supersede(
        MemorySupersessionRequest(
            replacement=replacement(),
            supersedes_memory_ids=(other["memory_id"],),
            reason="wrong lineage",
        )
    )

    assert result["ok"] is False
    assert "exact memory lineage" in result["error"]
    assert db.semantic_items == before


@pytest.mark.asyncio
async def test_lower_authority_replacement_cannot_supersede_stronger_memory(runtime):
    memory, db, lineage = runtime
    old = await seed(memory, authority=0.95)
    before = list(db.semantic_items)

    result = await lineage.supersede(
        MemorySupersessionRequest(
            replacement=replacement(authority=0.7),
            supersedes_memory_ids=(old["memory_id"],),
            reason="weaker source",
        )
    )

    assert result["ok"] is False
    assert "authority" in result["error"]
    assert result["required_authority"] == 0.95
    assert db.semantic_items == before


@pytest.mark.asyncio
async def test_replacement_must_differ_from_superseded_content(runtime):
    memory, db, lineage = runtime
    old = await seed(memory, content="Detroit")
    before = list(db.semantic_items)

    result = await lineage.supersede(
        MemorySupersessionRequest(
            replacement=replacement(content="Detroit"),
            supersedes_memory_ids=(old["memory_id"],),
            reason="not actually a new version",
        )
    )

    assert result["ok"] is False
    assert "must differ" in result["error"]
    assert db.semantic_items == before


@pytest.mark.asyncio
async def test_sensitive_supersession_cannot_bypass_memory_approval_guard(runtime):
    memory, db, _lineage = runtime
    old = await seed(memory)
    guarded = MemoryLineageService(memory)
    before = list(db.semantic_items)

    result = await guarded.supersede(
        MemorySupersessionRequest(
            replacement=replacement(sensitive=True),
            supersedes_memory_ids=(old["memory_id"],),
            reason="sensitive change",
            sensitive=True,
        )
    )

    assert result["ok"] is False
    assert "approval" in result["error"]
    assert result["phase"] == "replacement"
    assert db.semantic_items == before


@pytest.mark.asyncio
async def test_existing_version_lookup_failure_fails_closed_before_write(runtime):
    memory, db, lineage = runtime
    old = await seed(memory)
    before = list(db.semantic_items)
    db.fail_list = True

    result = await lineage.supersede(
        MemorySupersessionRequest(
            replacement=replacement(),
            supersedes_memory_ids=(old["memory_id"],),
            reason="cannot inspect lineage",
        )
    )

    assert result["ok"] is False
    assert "could not be verified" in result["error"]
    assert db.semantic_items == before
