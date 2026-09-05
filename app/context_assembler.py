from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.memory_scope import ScopedMemory


@dataclass(frozen=True)
class ContextBundle:
    memory_context: str
    retrieval_context: str
    citations: list[dict[str, Any]]
    namespaces: list[str]
    total_chars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_context": self.memory_context,
            "retrieval_context": self.retrieval_context,
            "citations": list(self.citations),
            "namespaces": list(self.namespaces),
            "total_chars": self.total_chars,
        }


class ContextAssembler:
    """Assemble bounded, scope-safe context for a single agent request.

    The assembler is intentionally independent from model prompting. It only
    selects context that is visible to the active project/conversation and keeps
    a hard character budget so retrieval cannot crowd out the user's request.
    """

    def __init__(self, *, max_chars: int = 24_000, memory_fraction: float = 0.35) -> None:
        if max_chars < 2_000:
            raise ValueError("max_chars must be at least 2000")
        if not 0.1 <= memory_fraction <= 0.8:
            raise ValueError("memory_fraction must be between 0.1 and 0.8")
        self.max_chars = max_chars
        self.memory_fraction = memory_fraction

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        if limit <= 1:
            return text[:limit]
        return text[: limit - 1].rstrip() + "…"

    async def assemble(
        self,
        *,
        query: str,
        memory_service: Any,
        rag_engine: Any,
        project_id: str | None = None,
        conversation_id: str | None = None,
        knowledge_base: str | None = None,
    ) -> ContextBundle:
        query = (query or "").strip()
        if not query:
            raise ValueError("query is required")

        namespaces = ScopedMemory.visible_namespaces(
            project_id=project_id,
            conversation_id=conversation_id,
        )
        memory_budget = max(500, int(self.max_chars * self.memory_fraction))
        retrieval_budget = self.max_chars - memory_budget

        memory = await memory_service.recall(
            query,
            project_id=project_id,
            conversation_id=conversation_id,
            limit=12,
        )
        memory_lines: list[str] = []
        for item in memory.get("results", []) if isinstance(memory, dict) else []:
            namespace = str(item.get("namespace") or "global")
            if namespace not in namespaces:
                continue
            source = str(item.get("source") or item.get("id") or "memory")
            content = str(item.get("content") or "").strip()
            if content:
                memory_lines.append(f"[{namespace} | {source}] {content}")
        memory_context = self._trim("\n".join(memory_lines), memory_budget)

        retrieval = await rag_engine.retrieve(
            query,
            project_id=project_id,
            knowledge_base=knowledge_base,
            limit=10,
        )
        retrieval_context = self._trim(
            str(retrieval.get("context") or "") if isinstance(retrieval, dict) else "",
            retrieval_budget,
        )
        citations = list(retrieval.get("citations", [])) if isinstance(retrieval, dict) else []

        total_chars = len(memory_context) + len(retrieval_context)
        if total_chars > self.max_chars:
            retrieval_context = self._trim(
                retrieval_context,
                max(0, self.max_chars - len(memory_context)),
            )
            total_chars = len(memory_context) + len(retrieval_context)

        return ContextBundle(
            memory_context=memory_context,
            retrieval_context=retrieval_context,
            citations=citations,
            namespaces=namespaces,
            total_chars=total_chars,
        )
