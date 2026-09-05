from __future__ import annotations

from typing import Any

from app.context_assembler import ContextAssembler, ContextBundle
from app.memory_service import MemoryService
from app.rag_engine import RAGEngine


class AgentContextRuntime:
    """Small integration boundary between the monolithic agent and v9 context systems.

    It composes the existing semantic store and workspace knowledge search into
    scoped long-term memory plus hybrid RAG without requiring the agent to know
    storage or ranking details.
    """

    def __init__(
        self,
        *,
        db: Any,
        semantic: Any,
        knowledge: Any,
        max_chars: int = 24_000,
    ) -> None:
        self.memory = MemoryService(db, semantic)
        self.rag = RAGEngine(semantic.search, knowledge.search)
        self.assembler = ContextAssembler(max_chars=max_chars)

    async def build(
        self,
        query: str,
        *,
        project_id: str | None = None,
        conversation_id: str | None = None,
        knowledge_base: str | None = None,
    ) -> ContextBundle:
        return await self.assembler.assemble(
            query=query,
            memory_service=self.memory,
            rag_engine=self.rag,
            project_id=project_id,
            conversation_id=conversation_id,
            knowledge_base=knowledge_base,
        )
