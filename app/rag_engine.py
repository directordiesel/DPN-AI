from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any, Awaitable, Callable


SemanticSearch = Callable[[str, str, int], Awaitable[dict[str, Any]]]
KeywordSearch = Callable[[str, int], dict[str, Any]]


@dataclass(frozen=True)
class RetrievalSource:
    source_id: str
    source_type: str
    namespace: str
    locator: str
    content: str
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float = 0.0
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["metadata"] = dict(self.metadata or {})
        return value


class RAGEngine:
    """Hybrid retrieval orchestration with deterministic scope and context limits.

    Semantic memory and workspace keyword search remain separate stores. This
    layer combines them, normalizes source metadata, deduplicates overlapping
    evidence, reranks deterministically, and builds an attributed context bundle.
    """

    def __init__(
        self,
        semantic_search: SemanticSearch,
        keyword_search: KeywordSearch,
        *,
        max_context_chars: int = 18_000,
        per_source_chars: int = 4_000,
    ) -> None:
        if max_context_chars < 1_000:
            raise ValueError("max_context_chars must be at least 1000")
        if per_source_chars < 250:
            raise ValueError("per_source_chars must be at least 250")
        self.semantic_search = semantic_search
        self.keyword_search = keyword_search
        self.max_context_chars = max_context_chars
        self.per_source_chars = per_source_chars

    @staticmethod
    def namespace_for(project_id: str | None = None, knowledge_base: str | None = None) -> str:
        if project_id and knowledge_base:
            return f"project:{project_id}:kb:{knowledge_base}"
        if project_id:
            return f"project:{project_id}"
        if knowledge_base:
            return f"kb:{knowledge_base}"
        return "global"

    @staticmethod
    def _fingerprint(content: str) -> str:
        normalized = re.sub(r"\s+", " ", (content or "").strip().lower())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _keyword_score(raw: Any) -> float:
        try:
            score = float(raw)
        except (TypeError, ValueError):
            return 0.0
        # SQLite FTS5 bm25 ranks better matches with lower/more-negative values.
        if score < 0:
            return min(1.0, abs(score) / (1.0 + abs(score)))
        return 1.0 / (1.0 + score)

    @staticmethod
    def _semantic_score(raw: Any) -> float:
        try:
            score = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(score, 1.0))

    @staticmethod
    def _source_id(source_type: str, locator: str, content: str) -> str:
        value = f"{source_type}\0{locator}\0{RAGEngine._fingerprint(content)}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    async def retrieve(
        self,
        query: str,
        *,
        project_id: str | None = None,
        knowledge_base: str | None = None,
        limit: int = 10,
        semantic_limit: int = 20,
        keyword_limit: int = 20,
    ) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "query is required", "sources": [], "context": ""}

        namespace = self.namespace_for(project_id, knowledge_base)
        semantic = await self.semantic_search(query, namespace, max(1, min(semantic_limit, 100)))
        keyword = self.keyword_search(query, max(1, min(keyword_limit, 100)))

        merged: dict[str, RetrievalSource] = {}

        for item in semantic.get("results", []) if isinstance(semantic, dict) else []:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            locator = str(item.get("source") or item.get("id") or "semantic")
            fingerprint = self._fingerprint(content)
            current = merged.get(fingerprint)
            source = RetrievalSource(
                source_id=self._source_id("semantic", locator, content),
                source_type="semantic",
                namespace=namespace,
                locator=locator,
                content=content,
                semantic_score=self._semantic_score(item.get("score")),
                metadata=dict(item.get("metadata") or {}),
            )
            if current is None or source.semantic_score > current.semantic_score:
                merged[fingerprint] = source

        for item in keyword.get("results", []) if isinstance(keyword, dict) else []:
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            locator = str(item.get("path") or item.get("source") or "workspace")
            fingerprint = self._fingerprint(content)
            kw_score = self._keyword_score(item.get("score"))
            current = merged.get(fingerprint)
            if current is None:
                merged[fingerprint] = RetrievalSource(
                    source_id=self._source_id("workspace", locator, content),
                    source_type="workspace",
                    namespace=namespace,
                    locator=locator,
                    content=content,
                    keyword_score=kw_score,
                    metadata={"path": locator},
                )
            else:
                merged[fingerprint] = RetrievalSource(
                    source_id=current.source_id,
                    source_type="hybrid" if current.source_type != "workspace" else current.source_type,
                    namespace=current.namespace,
                    locator=current.locator or locator,
                    content=current.content,
                    semantic_score=current.semantic_score,
                    keyword_score=max(current.keyword_score, kw_score),
                    metadata={**(current.metadata or {}), "path": locator},
                )

        reranked: list[RetrievalSource] = []
        for source in merged.values():
            hybrid_bonus = 0.08 if source.semantic_score > 0 and source.keyword_score > 0 else 0.0
            score = min(1.0, source.semantic_score * 0.68 + source.keyword_score * 0.32 + hybrid_bonus)
            reranked.append(RetrievalSource(
                source_id=source.source_id,
                source_type=source.source_type,
                namespace=source.namespace,
                locator=source.locator,
                content=source.content,
                semantic_score=source.semantic_score,
                keyword_score=source.keyword_score,
                rerank_score=round(score, 6),
                metadata=source.metadata,
            ))

        reranked.sort(key=lambda item: (-item.rerank_score, item.locator, item.source_id))
        selected = reranked[:max(1, min(limit, 50))]

        context_parts: list[str] = []
        citations: list[dict[str, Any]] = []
        used = 0
        for index, source in enumerate(selected, start=1):
            remaining = self.max_context_chars - used
            if remaining <= 0:
                break
            body = source.content[: min(self.per_source_chars, remaining)]
            label = f"[S{index}] {source.locator}"
            block = f"{label}\n{body}".strip()
            if used + len(block) > self.max_context_chars:
                block = block[: max(0, self.max_context_chars - used)]
            if not block:
                break
            context_parts.append(block)
            citations.append({
                "ref": f"S{index}",
                "source_id": source.source_id,
                "source_type": source.source_type,
                "namespace": source.namespace,
                "locator": source.locator,
                "score": source.rerank_score,
            })
            used += len(block) + 2

        return {
            "ok": True,
            "query": query,
            "namespace": namespace,
            "sources": [item.to_dict() for item in selected],
            "citations": citations,
            "context": "\n\n".join(context_parts),
            "context_chars": min(used, self.max_context_chars),
            "deduplicated_count": len(merged),
        }
