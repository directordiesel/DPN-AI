from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Protocol

from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, EvidenceNode, ResearchTask, ResearchWorkstream
from app.research_intelligence import ResearchSource


class DocumentResearchRuntimeProtocol(Protocol):
    async def retrieve(
        self,
        query: str,
        *,
        project_id: str | None = None,
        knowledge_base: str | None = None,
        limit: int = 10,
        semantic_limit: int = 20,
        keyword_limit: int = 20,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DocumentWorkerResult:
    task_id: str
    namespace: str
    source_count: int
    evidence_count: int
    context_chars: int


class DeepResearchDocumentWorker:
    """Adapts the existing scoped RAG runtime into the v10 evidence graph.

    The worker never opens files directly. It relies on the mature RAG layer for
    scoped semantic/keyword retrieval, then independently verifies namespace and
    provenance before committing evidence to the graph.
    """

    def __init__(
        self,
        runtime: DocumentResearchRuntimeProtocol,
        *,
        project_id: str | None = None,
        knowledge_base: str | None = None,
        max_sources: int = 12,
        max_excerpt_chars: int = 8_000,
    ) -> None:
        if not 1 <= max_sources <= 50:
            raise ValueError("max_sources must be between 1 and 50")
        if not 256 <= max_excerpt_chars <= 20_000:
            raise ValueError("max_excerpt_chars must be between 256 and 20000")
        self.runtime = runtime
        self.project_id = (project_id or "").strip() or None
        self.knowledge_base = (knowledge_base or "").strip() or None
        self.max_sources = max_sources
        self.max_excerpt_chars = max_excerpt_chars

    def expected_namespace(self) -> str:
        if self.project_id and self.knowledge_base:
            return f"project:{self.project_id}:kb:{self.knowledge_base}"
        if self.project_id:
            return f"project:{self.project_id}"
        if self.knowledge_base:
            return f"kb:{self.knowledge_base}"
        return "global"

    @staticmethod
    def _bounded_score(raw: Any, *, default: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(value):
            return default
        return max(0.0, min(value, 1.0))

    @staticmethod
    def _evidence_id(task_id: str, source_id: str) -> str:
        digest = hashlib.sha256(f"{task_id}\0{source_id}".encode("utf-8")).hexdigest()[:20]
        return f"doc-{digest}"

    def _stage_source(self, task: ResearchTask, raw: dict[str, Any], namespace: str) -> tuple[ResearchSource, EvidenceNode]:
        source_id = str(raw.get("source_id") or "").strip()
        source_type = str(raw.get("source_type") or "document").strip() or "document"
        source_namespace = str(raw.get("namespace") or "").strip()
        locator = str(raw.get("locator") or "").strip()
        content = str(raw.get("content") or "").strip()
        metadata = dict(raw.get("metadata") or {})

        if not source_id or not locator or not content:
            raise DeepResearchError("document source is missing required provenance")
        if source_namespace != namespace:
            raise DeepResearchError("document source escaped the requested retrieval namespace")

        quality = self._bounded_score(raw.get("rerank_score"), default=0.0)
        freshness = self._bounded_score(metadata.get("freshness_score"), default=0.5)
        title = str(metadata.get("title") or metadata.get("filename") or locator).strip() or locator
        excerpt = content[: self.max_excerpt_chars]

        source = ResearchSource(
            source_id=source_id,
            title=title,
            url=f"dpn://retrieval/{source_id}",
            domain="local.dpn",
            snippet=excerpt,
            content=content,
            source_type=source_type,
            authority_score=quality,
            freshness_score=freshness,
            relevance_score=quality,
            quality_score=quality,
            metadata={
                **metadata,
                "namespace": namespace,
                "locator": locator,
                "local_retrieval": True,
            },
        )
        node = EvidenceNode(
            evidence_id=self._evidence_id(task.task_id, source_id),
            source_id=source_id,
            source_type=source_type,
            title=title,
            locator=locator,
            excerpt=excerpt,
            quality_score=quality,
            freshness_score=freshness,
            metadata={
                "task_id": task.task_id,
                "workstream": task.workstream.value,
                "namespace": namespace,
                "local_retrieval": True,
            },
        )
        node.validate()
        return source, node

    async def execute(self, task: ResearchTask, graph: EvidenceGraph) -> DocumentWorkerResult:
        task.validate()
        if task.workstream != ResearchWorkstream.DOCUMENTS:
            raise DeepResearchError("document worker only accepts document research tasks")

        expected_namespace = self.expected_namespace()
        bundle = await self.runtime.retrieve(
            task.query,
            project_id=self.project_id,
            knowledge_base=self.knowledge_base,
            limit=self.max_sources,
            semantic_limit=min(max(self.max_sources * 2, 10), 100),
            keyword_limit=min(max(self.max_sources * 2, 10), 100),
        )
        if not isinstance(bundle, dict) or not bundle.get("ok"):
            raise DeepResearchError("document research runtime did not return trusted evidence")
        namespace = str(bundle.get("namespace") or "").strip()
        if namespace != expected_namespace:
            raise DeepResearchError("document research runtime returned the wrong namespace")

        raw_sources = bundle.get("sources", [])
        if not isinstance(raw_sources, list):
            raise DeepResearchError("document research sources must be a list")
        raw_sources = raw_sources[: self.max_sources]

        staged: list[tuple[ResearchSource, EvidenceNode]] = []
        seen_source_ids: set[str] = set()
        for raw in raw_sources:
            if not isinstance(raw, dict):
                raise DeepResearchError("document research source must be an object")
            source, node = self._stage_source(task, raw, namespace)
            if source.source_id in seen_source_ids:
                raise DeepResearchError("duplicate document source id in worker result")
            seen_source_ids.add(source.source_id)
            staged.append((source, node))

        if task.required and not staged:
            raise DeepResearchError("required document task produced no admissible evidence")

        # Preflight against live graph so the admission batch is all-or-nothing.
        existing_sources = {item.source_id: item for item in graph.sources}
        existing_evidence = {item.evidence_id: item for item in graph.evidence}
        for source, node in staged:
            current_source = existing_sources.get(source.source_id)
            if current_source is not None and current_source != source:
                raise DeepResearchError("source id collision detected before graph commit")
            current_node = existing_evidence.get(node.evidence_id)
            if current_node is not None and current_node != node:
                raise DeepResearchError("evidence id collision detected before graph commit")

        for source, node in staged:
            graph.add_source(source)
            graph.add_evidence(node)

        context_chars = bundle.get("context_chars", 0)
        try:
            context_chars = max(0, int(context_chars))
        except (TypeError, ValueError):
            context_chars = 0
        return DocumentWorkerResult(
            task_id=task.task_id,
            namespace=namespace,
            source_count=len(staged),
            evidence_count=len(staged),
            context_chars=context_chars,
        )


__all__ = ["DeepResearchDocumentWorker", "DocumentResearchRuntimeProtocol", "DocumentWorkerResult"]
