from __future__ import annotations

import pytest

from app.advanced_layered_memory_v10 import AdvancedLayeredMemory, MemoryContext, MemoryProvenance, MemoryWriteRequest
from app.memory_service import MemoryService
from app.memory_tool_runtime_v10 import GovernedMemoryToolRuntime, TrustedMemoryToolContext
from app.permission_engine import PermissionEngine, PermissionMode, RiskLevel
from app.tool_permission_runtime import ToolPermissionRuntime


class FakeDB:
    def __init__(self):
        self.memories = {}
        self.semantic_items = []

    def upsert_memory(self, key, value):
        self.memories[key] = value

    def delete_memory(self, key):
        self.memories.pop(key, None)

    def list_semantic_items(self, namespace, limit=5000):
        return [item for item in self.semantic_items if item["namespace"] == namespace][:limit]


class FakeSemantic:
    def __init__(self, db):
        self.db = db

    async def add(self, content, namespace="global", source="manual", metadata=None, item_id=None):
        item = {"id": item_id, "namespace": namespace, "source": source, "content": content, "metadata": dict(metadata or {})}
        self.db.semantic_items = [entry for entry in self.db.semantic_items if entry["id"] != item_id]
        self.db.semantic_items.append(item)
        return {"ok": True, "item": item, "dimensions": 2}

    async def search_many(self, query, namespaces, limit=8):
        results = []
        for item in self.db.semantic_items:
            if item["namespace"] in namespaces:
                candidate = dict(item)
                candidate["score"] = 0.9
                results.append(candidate)
        return {"ok": True, "model": "fake", "results": results[:limit]}


@pytest.fixture
def governed():
    db = FakeDB()
    memory = AdvancedLayeredMemory(MemoryService(db, FakeSemantic(db)))
    runtime = GovernedMemoryToolRuntime(
        memory,
        context=TrustedMemoryToolContext(organization_id="dpn", user_id="u1", project_id="p1", conversation_id="c1"),
    )
    return runtime, db


@pytest.mark.asyncio
async def test_tool_runtime_uses_trusted_scope_context_and_cannot_cross_user_boundary(governed):
    runtime, db = governed
    stored = await runtime.remember(
        layer="user",
        key="preference",
        content="alpha",
        knowledge_class="fact",
        source_type="test",
        source_id="e1",
    )
    assert stored["ok"] is True
    assert stored["scope_id"] == "user:u1"
    assert all(item["namespace"] != "user:u2" for item in db.semantic_items)

    recalled = await runtime.recall("preference", layers=["user"])
    assert recalled["ok"] is True
    assert recalled["namespaces"] == ["global", "organization:dpn", "user:u1", "project:p1", "conversation:c1"]
    assert [item["content"] for item in recalled["results"]] == ["alpha"]


@pytest.mark.asyncio
async def test_sensitive_write_still_fails_closed_without_external_approval_guard(governed):
    runtime, db = governed
    result = await runtime.remember(
        layer="user",
        key="secret_pref",
        content="private",
        knowledge_class="fact",
        source_type="test",
        source_id="e2",
        sensitive=True,
    )
    assert result["ok"] is False
    assert "approval" in result["error"]
    assert db.semantic_items == []


def test_lineage_inspection_requires_scope_identity_present_in_trusted_context(governed):
    runtime, _db = governed
    report = runtime.inspect_lineage(scope="project")
    assert report["ok"] is True
    assert report["report"]["scope_id"] == "project:p1"

    other = GovernedMemoryToolRuntime(runtime.memory, context=TrustedMemoryToolContext(user_id="u1"))
    denied = other.inspect_lineage(scope="project")
    assert denied["ok"] is False
    assert "project_id" in denied["error"]


@pytest.mark.asyncio
async def test_supersession_preserves_old_version_and_requires_evidence(governed):
    runtime, db = governed
    first = await runtime.remember(
        layer="project",
        key="region",
        content="Detroit",
        knowledge_class="fact",
        source_type="test",
        source_id="old",
        authority=0.7,
    )
    assert first["ok"] is True

    rejected = await runtime.supersede(
        layer="project",
        key="region",
        content="Chicago",
        knowledge_class="fact",
        source_type="test",
        source_id="new",
        evidence_ids=[],
        supersedes_memory_ids=[first["memory_id"]],
        reason="verified update",
        authority=0.8,
    )
    assert rejected["ok"] is False
    assert "evidence" in rejected["error"]

    accepted = await runtime.supersede(
        layer="project",
        key="region",
        content="Chicago",
        knowledge_class="fact",
        source_type="test",
        source_id="new",
        evidence_ids=["evidence-1"],
        supersedes_memory_ids=[first["memory_id"]],
        reason="verified update",
        authority=0.8,
    )
    assert accepted["ok"] is True
    contents = [item["content"] for item in db.semantic_items]
    assert "Detroit" in contents
    assert "Chicago" in contents


def test_tool_permission_runtime_always_approval_gates_supersession():
    engine = PermissionEngine(PermissionMode.ALWAYS_ALLOW)
    engine.set_tool_rule("dpn_memory_supersede", PermissionMode.ALWAYS_ALLOW, RiskLevel.WRITE)
    runtime = ToolPermissionRuntime(engine)
    authorization = runtime.authorize(
        tool_name="dpn_memory_supersede",
        declared_risk="write",
        gate=None,
        permissions={"approval_mode": "full"},
        use_v9_policy=True,
        arguments={"reason": "new evidence"},
    )
    assert authorization.allowed is False
    assert authorization.approval_required is True
    assert "memory supersession" in authorization.reason.lower()


@pytest.mark.asyncio
async def test_derived_memory_requires_evidence_through_tool_facade(governed):
    runtime, _db = governed
    result = await runtime.remember(
        layer="semantic",
        key="derived",
        content="derived conclusion",
        knowledge_class="derived",
        source_type="agent",
        source_id="run-1",
        evidence_ids=[],
    )
    assert result["ok"] is False
    assert "requires evidence ids" in result["error"]
