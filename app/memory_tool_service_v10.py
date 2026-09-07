from __future__ import annotations

from typing import Any, Callable

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    MemoryContext,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.memory_compaction_v10 import MemoryCompactionError, MemoryCompactionService
from app.memory_lineage_v10 import MemoryLineageService, MemorySupersessionRequest
from app.memory_scope import MemoryScope, ScopedMemory
from app.memory_service import MemoryService


ScopeAuthorizer = Callable[[MemoryScope, MemoryContext], bool]


class GovernedMemoryToolService:
    """Bounded tool-facing adapter for v10 layered memory.

    The model-visible tool surface may name scope identifiers, but those identifiers
    are never trusted as authority. Every non-global scope must be approved by a
    host-injected scope_authorizer. Without one, non-global access fails closed.

    The service exposes no raw database, semantic-store, deletion, compaction
    mutation, or approval override. Sensitive persistence is not accepted through
    this tool surface; higher-trust internal callers must use an explicitly governed
    AdvancedLayeredMemory integration.
    """

    def __init__(self, db: Any, semantic: Any, *, scope_authorizer: ScopeAuthorizer | None = None) -> None:
        self.memory = AdvancedLayeredMemory(MemoryService(db, semantic))
        self.lineage = MemoryLineageService(self.memory)
        self.compaction = MemoryCompactionService(self.memory)
        self.scope_authorizer = scope_authorizer

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

    @staticmethod
    def _scope_for_identifier(name: str) -> MemoryScope:
        return {
            "organization_id": MemoryScope.ORGANIZATION,
            "user_id": MemoryScope.USER,
            "project_id": MemoryScope.PROJECT,
            "conversation_id": MemoryScope.CONVERSATION,
        }[name]

    def _authorize_context(self, context: MemoryContext) -> tuple[bool, str]:
        values = {
            "organization_id": context.organization_id,
            "user_id": context.user_id,
            "project_id": context.project_id,
            "conversation_id": context.conversation_id,
        }
        for name, value in values.items():
            if not value:
                continue
            scope = self._scope_for_identifier(name)
            if self.scope_authorizer is None:
                return False, f"{scope.value} memory scope requires trusted host authorization"
            try:
                allowed = bool(self.scope_authorizer(scope, context))
            except Exception:
                allowed = False
            if not allowed:
                return False, f"{scope.value} memory scope authorization denied"
        return True, ""

    def _authorized_context(
        self,
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
    ) -> tuple[MemoryContext | None, str]:
        context = self._context(organization_id, user_id, project_id, conversation_id)
        allowed, reason = self._authorize_context(context)
        return (context, "") if allowed else (None, reason)

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
        context, error = self._authorized_context(organization_id, user_id, project_id, conversation_id)
        if context is None:
            return {"ok": False, "error": error, "stored": False}
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
            context=context,
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
        context, error = self._authorized_context(organization_id, user_id, project_id, conversation_id)
        if context is None:
            return {"ok": False, "error": error, "results": []}
        return await self.memory.recall(query, context=context, layers=layers, limit=limit)

    def inspect_lineage(
        self,
        *,
        scope: str,
        organization_id: str = "",
        user_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
    ) -> dict[str, Any]:
        context, error = self._authorized_context(organization_id, user_id, project_id, conversation_id)
        if context is None:
            return {"ok": False, "error": error, "report": None}
        try:
            scope_id = ScopedMemory.scope_id(
                MemoryScope(scope),
                organization_id=context.organization_id,
                user_id=context.user_id,
                project_id=context.project_id,
                conversation_id=context.conversation_id,
            )
            return {"ok": True, "report": self.compaction.analyze(scope_id).to_dict()}
        except (TypeError, ValueError, MemoryCompactionError) as exc:
            return {"ok": False, "error": str(exc), "report": None}

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
        context, error = self._authorized_context(organization_id, user_id, project_id, conversation_id)
        if context is None:
            return {"ok": False, "error": error, "stored": False}
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
            context=context,
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


__all__ = ["GovernedMemoryToolService", "ScopeAuthorizer"]
