from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    KnowledgeClass,
    MemoryContext,
    MemoryLayer,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.memory_compaction_v10 import MemoryCompactionError, MemoryCompactionService
from app.memory_lineage_v10 import MemoryLineageService, MemorySupersessionRequest
from app.memory_scope import MemoryScope, ScopedMemory


class MemoryToolRuntimeError(ValueError):
    """Raised when a governed memory tool request cannot be executed safely."""


@dataclass(frozen=True)
class TrustedMemoryToolContext:
    """Scope identity injected by the host runtime, never supplied by model tool arguments."""

    organization_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None

    def memory_context(self) -> MemoryContext:
        return MemoryContext(
            organization_id=self.organization_id,
            user_id=self.user_id,
            project_id=self.project_id,
            conversation_id=self.conversation_id,
        )


class GovernedMemoryToolRuntime:
    """Agent-facing facade over v10 memory without widening authority.

    Scope identifiers are constructor-injected trusted context. Tool arguments may
    choose a memory layer/scope only within that trusted context; they cannot supply
    arbitrary tenant/user/project/conversation identifiers. Persistent writes still
    flow through AdvancedLayeredMemory, including its sensitive-write approval guard.
    Supersession still flows through MemoryLineageService and is additionally marked
    approval-gated by ToolPermissionRuntime under the tool name dpn_memory_supersede.
    """

    MAX_EVIDENCE_IDS = 128

    def __init__(self, memory: AdvancedLayeredMemory, *, context: TrustedMemoryToolContext) -> None:
        self.memory = memory
        self.context = context
        self.lineage = MemoryLineageService(memory)
        self.compaction = MemoryCompactionService(memory)

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _evidence_ids(cls, values: Iterable[str] | None) -> tuple[str, ...]:
        items = tuple(cls._clean(value) for value in (values or ()))
        if any(not value for value in items):
            raise MemoryToolRuntimeError("evidence ids cannot be empty")
        if len(items) != len(set(items)):
            raise MemoryToolRuntimeError("evidence ids must be unique")
        if len(items) > cls.MAX_EVIDENCE_IDS:
            raise MemoryToolRuntimeError("evidence id limit exceeded")
        return items

    def _scope_id(self, scope: MemoryScope | str) -> str:
        return ScopedMemory.scope_id(
            scope,
            organization_id=self.context.organization_id,
            user_id=self.context.user_id,
            project_id=self.context.project_id,
            conversation_id=self.context.conversation_id,
        )

    async def recall(self, query: str, *, layers: Iterable[MemoryLayer | str] | None = None, limit: int = 8) -> dict[str, Any]:
        return await self.memory.recall(
            query,
            context=self.context.memory_context(),
            layers=layers,
            limit=limit,
        )

    async def remember(
        self,
        *,
        layer: MemoryLayer | str,
        key: str,
        content: str,
        knowledge_class: KnowledgeClass | str,
        source_type: str,
        source_id: str,
        evidence_ids: Iterable[str] | None = None,
        confidence: float = 1.0,
        authority: float = 0.5,
        scope: MemoryScope | str | None = None,
        ttl_seconds: int | None = None,
        sensitive: bool = False,
    ) -> dict[str, Any]:
        try:
            evidence = self._evidence_ids(evidence_ids)
        except MemoryToolRuntimeError as exc:
            return {"ok": False, "error": str(exc), "stored": False}
        request = MemoryWriteRequest(
            layer=layer,
            key=key,
            content=content,
            knowledge_class=knowledge_class,
            provenance=MemoryProvenance(
                source_type=self._clean(source_type),
                source_id=self._clean(source_id),
                evidence_ids=evidence,
                confidence=float(confidence),
                authority=float(authority),
            ),
            context=self.context.memory_context(),
            scope=scope,
            ttl_seconds=ttl_seconds,
            sensitive=bool(sensitive),
        )
        return await self.memory.remember(request)

    def inspect_lineage(self, *, scope: MemoryScope | str) -> dict[str, Any]:
        try:
            scope_id = self._scope_id(scope)
            return {"ok": True, "report": self.compaction.analyze(scope_id).to_dict()}
        except (TypeError, ValueError, MemoryCompactionError) as exc:
            return {"ok": False, "error": str(exc), "report": None}

    async def supersede(
        self,
        *,
        layer: MemoryLayer | str,
        key: str,
        content: str,
        knowledge_class: KnowledgeClass | str,
        source_type: str,
        source_id: str,
        evidence_ids: Iterable[str],
        supersedes_memory_ids: Iterable[str],
        reason: str,
        confidence: float = 1.0,
        authority: float = 0.5,
        scope: MemoryScope | str | None = None,
        ttl_seconds: int | None = None,
        sensitive: bool = False,
    ) -> dict[str, Any]:
        try:
            evidence = self._evidence_ids(evidence_ids)
            targets = tuple(self._clean(value) for value in supersedes_memory_ids)
        except MemoryToolRuntimeError as exc:
            return {"ok": False, "error": str(exc), "stored": False}
        replacement = MemoryWriteRequest(
            layer=layer,
            key=key,
            content=content,
            knowledge_class=knowledge_class,
            provenance=MemoryProvenance(
                source_type=self._clean(source_type),
                source_id=self._clean(source_id),
                evidence_ids=evidence,
                confidence=float(confidence),
                authority=float(authority),
            ),
            context=self.context.memory_context(),
            scope=scope,
            ttl_seconds=ttl_seconds,
            sensitive=bool(sensitive),
        )
        return await self.lineage.supersede(
            MemorySupersessionRequest(
                replacement=replacement,
                supersedes_memory_ids=targets,
                reason=reason,
                sensitive=bool(sensitive),
            )
        )


__all__ = ["GovernedMemoryToolRuntime", "MemoryToolRuntimeError", "TrustedMemoryToolContext"]
