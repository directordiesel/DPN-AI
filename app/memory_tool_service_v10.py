from __future__ import annotations

from typing import Any

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    MemoryContext,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.memory_compaction_v10 import MemoryCompactionService
from app.memory_lineage_v10 import MemoryLineageService, MemorySupersessionRequest
from app.memory_service import MemoryService


class GovernedMemoryToolService:
    """Bounded tool-facing adapter for v10 layered memory.

    This service intentionally exposes no raw database, semantic-store, deletion,
    compaction mutation, or approval override. Sensitive persistence is not accepted
    through the tool surface; higher-trust internal callers must use the injected
    approval guard on AdvancedLayeredMemory directly.
    """

    def __init__(self, db: Any, semantic: Any) -> None:
        self.memory = AdvancedLayeredMemory(MemoryService(db, semantic))
        self.lineage = MemoryLineageService(self.memory)
        self.compaction = MemoryCompactionService(self.memory)

    @staticmethod
    def _context(
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
    ) -> MemoryContext:
        return MemoryContext(
            organization_id=organization_id.strip() or None,
            user_id=user_id.strip() or None,
            project_id=project_id.strip() or None,
            conversation_id=conversation_id.strip() or None,
        )

    async def remember(
        self,
        *,
        layer: str,
        key: str,
        content: str,
        knowledge_class: str,
        source_type: str,
        source_id: str,
        evidence_ids: list[str] | None = None,
        confidence: float = 1.0,
        authority: float = 0.5,
        scope: str | None = None,
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        request = MemoryWriteRequest(
            layer=layer,
            key=key,
            content=content,
            knowledge_class=knowledge_class,
            provenance=MemoryProvenance(
                source_type=source_type,
                source_id=source_id,
                evidence_ids=tuple(evidence_ids or ()),
                confidence=confidence,
                authority=authority,
            ),
            context=self._context(organization_id, user_id, project_id, conversation_id),
            scope=scope,
            ttl_seconds=ttl_seconds,
            sensitive=False,
        )
        return await self.memory.remember(request)

    async def recall(
        self,
        *,
        query: str,
        layers: list[str] | None = None,
        limit: int = 8,
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
    ) -> dict[str, Any]:
        return await self.memory.recall(
            query,
            context=self._context(organization_id, user_id, project_id, conversation_id),
            layers=layers,
            limit=limit,
        )

    def inspect_lineage(
        self,
        *,
        layer: str,
        key: str,
        scope: str | None = None,
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
    ) -> dict[str, Any]:
        return self.compaction.analyze(
            layer=layer,
            key=key,
            scope=scope,
            context=self._context(organization_id, user_id, project_id, conversation_id),
        )

    async def supersede(
        self,
        *,
        layer: str,
        key: str,
        content: str,
        knowledge_class: str,
        source_type: str,
        source_id: str,
        evidence_ids: list[str],
        supersedes_memory_ids: list[str],
        reason: str,
        confidence: float = 1.0,
        authority: float = 0.5,
        scope: str | None = None,
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
    ) -> dict[str, Any]:
        replacement = MemoryWriteRequest(
            layer=layer,
            key=key,
            content=content,
            knowledge_class=knowledge_class,
            provenance=MemoryProvenance(
                source_type=source_type,
                source_id=source_id,
                evidence_ids=tuple(evidence_ids or ()),
                confidence=confidence,
                authority=authority,
            ),
            context=self._context(organization_id, user_id, project_id, conversation_id),
            scope=scope,
            sensitive=False,
        )
        return await self.lineage.supersede(
            MemorySupersessionRequest(
                replacement=replacement,
                supersedes_memory_ids=tuple(supersedes_memory_ids or ()),
                reason=reason,
                sensitive=False,
            )
        )


__all__ = ["GovernedMemoryToolService"]
