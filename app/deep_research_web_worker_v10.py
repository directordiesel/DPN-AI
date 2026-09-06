from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Protocol

from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, EvidenceNode, ResearchTask, ResearchWorkstream
from app.research_intelligence import ResearchSource


class WebResearchRuntimeProtocol(Protocol):
    async def research(self, query: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WebWorkerResult:
    task_id: str
    source_count: int
    evidence_count: int
    partial: bool
    fetch_failure_count: int


class DeepResearchWebWorker:
    """Adapts the existing bounded WebResearchRuntime into the v10 evidence graph."""

    def __init__(self, runtime: WebResearchRuntimeProtocol, *, max_sources: int = 12, max_excerpt_chars: int = 8_000) -> None:
        if not 1 <= max_sources <= 50:
            raise ValueError("max_sources must be between 1 and 50")
        if not 256 <= max_excerpt_chars <= 20_000:
            raise ValueError("max_excerpt_chars must be between 256 and 20000")
        self.runtime = runtime
        self.max_sources = max_sources
        self.max_excerpt_chars = max_excerpt_chars

    @staticmethod
    def _source_from_dict(raw: dict[str, Any]) -> ResearchSource:
        source = ResearchSource(
            source_id=str(raw.get("source_id") or "").strip(),
            title=str(raw.get("title") or "").strip(),
            url=str(raw.get("url") or "").strip(),
            domain=str(raw.get("domain") or "").strip(),
            snippet=str(raw.get("snippet") or "").strip(),
            content=str(raw.get("content") or "").strip(),
            published_at=str(raw.get("published_at")) if raw.get("published_at") else None,
            source_type=str(raw.get("source_type") or "web").strip() or "web",
            authority_score=float(raw.get("authority_score", 0.0)),
            freshness_score=float(raw.get("freshness_score", 0.0)),
            relevance_score=float(raw.get("relevance_score", 0.0)),
            quality_score=float(raw.get("quality_score", 0.0)),
            metadata=dict(raw.get("metadata") or {}),
        )
        if not source.source_id or not source.url or not source.domain:
            raise DeepResearchError("web source is missing required provenance")
        return source

    @staticmethod
    def _evidence_id(task_id: str, source_id: str) -> str:
        digest = hashlib.sha256(f"{task_id}\0{source_id}".encode("utf-8")).hexdigest()[:20]
        return f"web-{digest}"

    async def execute(self, task: ResearchTask, graph: EvidenceGraph) -> WebWorkerResult:
        task.validate()
        if task.workstream != ResearchWorkstream.WEB:
            raise DeepResearchError("web worker only accepts web research tasks")

        bundle = await self.runtime.research(task.query)
        if not isinstance(bundle, dict) or not bundle.get("ok"):
            raise DeepResearchError("web research runtime did not return trusted evidence")

        raw_sources = bundle.get("sources", [])
        if not isinstance(raw_sources, list):
            raise DeepResearchError("web research sources must be a list")
        if len(raw_sources) > self.max_sources:
            raw_sources = raw_sources[: self.max_sources]

        staged: list[tuple[ResearchSource, EvidenceNode]] = []
        seen_source_ids: set[str] = set()
        for raw in raw_sources:
            if not isinstance(raw, dict):
                raise DeepResearchError("web research source must be an object")
            source = self._source_from_dict(raw)
            if source.source_id in seen_source_ids:
                raise DeepResearchError("duplicate web source id in worker result")
            seen_source_ids.add(source.source_id)
            excerpt = (source.content or source.snippet).strip()[: self.max_excerpt_chars]
            if not excerpt:
                continue
            node = EvidenceNode(
                evidence_id=self._evidence_id(task.task_id, source.source_id),
                source_id=source.source_id,
                source_type=source.source_type,
                title=source.title or source.domain,
                locator=source.url,
                excerpt=excerpt,
                quality_score=source.quality_score,
                freshness_score=source.freshness_score,
                metadata={
                    "task_id": task.task_id,
                    "workstream": task.workstream.value,
                    "domain": source.domain,
                    "published_at": source.published_at,
                    "authority_score": source.authority_score,
                    "relevance_score": source.relevance_score,
                },
            )
            node.validate()
            staged.append((source, node))

        if task.required and not staged:
            raise DeepResearchError("required web task produced no admissible evidence")

        # Preflight collisions against the live graph so admission remains all-or-nothing.
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

        failures = bundle.get("fetch_failures", [])
        failure_count = len(failures) if isinstance(failures, list) else 0
        return WebWorkerResult(
            task_id=task.task_id,
            source_count=len(staged),
            evidence_count=len(staged),
            partial=bool(bundle.get("partial")),
            fetch_failure_count=failure_count,
        )


__all__ = ["DeepResearchWebWorker", "WebResearchRuntimeProtocol", "WebWorkerResult"]
