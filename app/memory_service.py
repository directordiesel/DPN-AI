from __future__ import annotations

from typing import Any

from app.db import Database
from app.memory_scope import MemoryScope, ScopedMemory
from app.semantic import SemanticMemory


class MemoryService:
    """Persistent scoped memory backed by the existing DB and semantic store.

    Key/value persistence uses a namespaced key for deterministic replacement.
    Semantic persistence uses the stable scoped memory id so updates replace the
    prior embedding instead of creating duplicate long-term memories.
    """

    def __init__(self, db: Database, semantic: SemanticMemory):
        self.db = db
        self.semantic = semantic

    @staticmethod
    def storage_key(scope_id: str, key: str) -> str:
        return f"v9:{scope_id}:{(key or '').strip().lower()}"

    async def remember(
        self,
        key: str,
        value: str,
        *,
        scope: MemoryScope | str = MemoryScope.GLOBAL,
        organization_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = ScopedMemory.build(
            key,
            value,
            scope=scope,
            organization_id=organization_id,
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
            source=source,
            metadata=metadata,
        )
        storage_key = self.storage_key(record.scope_id, record.key)
        self.db.upsert_memory(storage_key, record.value)
        semantic_metadata = {
            **record.metadata,
            "memory_id": record.memory_id,
            "memory_key": record.key,
            "memory_scope": record.scope.value,
            "scope_id": record.scope_id,
        }
        semantic_result = await self.semantic.add(
            record.value,
            namespace=record.scope_id,
            source=record.source,
            metadata=semantic_metadata,
            item_id=record.memory_id,
        )
        if not semantic_result.get("ok"):
            # Fail closed for semantic persistence: remove the KV write so callers
            # never receive a success for a partially remembered record.
            self.db.delete_memory(storage_key)
            return {
                "ok": False,
                "error": semantic_result.get("error") or "semantic persistence failed",
            }
        return {
            "ok": True,
            "memory": record.to_dict(),
            "storage_key": storage_key,
            "dimensions": semantic_result.get("dimensions", 0),
        }

    async def recall(
        self,
        query: str,
        *,
        organization_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        namespaces = ScopedMemory.visible_namespaces(
            organization_id=organization_id,
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        result = await self.semantic.search_many(query, namespaces, limit=limit)
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "query": query,
            "namespaces": namespaces,
            "results": result.get("results", []),
            "model": result.get("model"),
        }
