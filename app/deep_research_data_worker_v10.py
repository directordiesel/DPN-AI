from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Protocol

from app.deep_research_engine_v10 import DeepResearchError, EvidenceGraph, EvidenceNode, ResearchTask, ResearchWorkstream
from app.research_intelligence import ResearchSource


class StructuredDataRuntimeProtocol(Protocol):
    async def read(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: str = "",
        order_direction: str = "ASC",
        limit: int = 100,
        search: bool = False,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DataQuerySpec:
    """Explicit bounded selection for a governed structured-data research task."""

    table: str
    columns: tuple[str, ...] = ()
    filters: tuple[tuple[str, Any], ...] = ()
    order_by: str = ""
    order_direction: str = "ASC"
    limit: int = 100

    def validate(self) -> None:
        if not self.table.strip():
            raise DeepResearchError("data research table is required")
        if len(self.columns) > 50:
            raise DeepResearchError("data research columns exceed the bounded limit")
        if len(self.filters) > 20:
            raise DeepResearchError("data research filters exceed the bounded limit")
        if self.order_direction.upper() not in {"ASC", "DESC"}:
            raise DeepResearchError("data research order direction must be ASC or DESC")
        if not 1 <= int(self.limit) <= 100:
            raise DeepResearchError("data research limit must be between 1 and 100")
        keys = [str(key) for key, _ in self.filters]
        if len(keys) != len(set(keys)):
            raise DeepResearchError("data research filter keys must be unique")


@dataclass(frozen=True)
class DataWorkerResult:
    task_id: str
    table: str
    row_count: int
    evidence_count: int
    connector_id: str


class DeepResearchDataWorker:
    """Adapts the governed read-only SQL connector into the v10 evidence graph.

    The worker never accepts raw SQL and never derives SQL from model text. A caller must
    provide a validated DataQuerySpec. Execution then remains inside the existing SQLite
    connector's table allowlist, identifier validation, parameterization, and mode=ro
    boundary. Returned provenance is independently revalidated before graph admission.
    """

    def __init__(
        self,
        runtime: StructuredDataRuntimeProtocol,
        *,
        connector_id: str = "sqlite:dpn-core",
        max_excerpt_chars: int = 4_000,
    ) -> None:
        if not connector_id.strip():
            raise ValueError("connector_id is required")
        if not 256 <= max_excerpt_chars <= 10_000:
            raise ValueError("max_excerpt_chars must be between 256 and 10000")
        self.runtime = runtime
        self.connector_id = connector_id.strip()
        self.max_excerpt_chars = max_excerpt_chars

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
    def _canonical_row(row: dict[str, Any]) -> str:
        try:
            return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise DeepResearchError("structured data row could not be serialized safely") from exc

    @staticmethod
    def _source_id(connector_id: str, database: str, table: str) -> str:
        digest = hashlib.sha256(f"{connector_id}\0{database}\0{table}".encode("utf-8")).hexdigest()[:20]
        return f"data-source-{digest}"

    @staticmethod
    def _evidence_id(task_id: str, source_id: str, row_index: int, canonical_row: str) -> str:
        digest = hashlib.sha256(
            f"{task_id}\0{source_id}\0{row_index}\0{canonical_row}".encode("utf-8")
        ).hexdigest()[:20]
        return f"data-{digest}"

    async def execute(self, task: ResearchTask, graph: EvidenceGraph, spec: DataQuerySpec) -> DataWorkerResult:
        task.validate()
        spec.validate()
        if task.workstream != ResearchWorkstream.DATA:
            raise DeepResearchError("data worker only accepts structured-data research tasks")

        bundle = await self.runtime.read(
            spec.table,
            columns=list(spec.columns) if spec.columns else None,
            filters=dict(spec.filters),
            order_by=spec.order_by,
            order_direction=spec.order_direction.upper(),
            limit=spec.limit,
            search=False,
        )
        if not isinstance(bundle, dict) or not bundle.get("ok"):
            raise DeepResearchError("structured data runtime did not return trusted evidence")
        if str(bundle.get("action") or "").strip().lower() != "read":
            raise DeepResearchError("structured data runtime escaped the read-only action boundary")

        result = bundle.get("result")
        provenance = bundle.get("provenance")
        if not isinstance(result, dict) or not isinstance(provenance, dict):
            raise DeepResearchError("structured data runtime returned malformed evidence")
        if str(result.get("table") or "") != spec.table or str(provenance.get("table") or "") != spec.table:
            raise DeepResearchError("structured data runtime returned evidence from the wrong table")
        if str(provenance.get("provider") or "").lower() != "sqlite":
            raise DeepResearchError("structured data runtime returned an unexpected provider")
        if provenance.get("read_only") is not True or provenance.get("parameterized") is not True:
            raise DeepResearchError("structured data provenance did not prove read-only parameterized execution")

        rows = result.get("rows")
        if not isinstance(rows, list):
            raise DeepResearchError("structured data rows must be a list")
        if len(rows) > spec.limit:
            raise DeepResearchError("structured data runtime exceeded the requested row limit")
        declared_count = result.get("row_count")
        try:
            declared_count = int(declared_count)
        except (TypeError, ValueError) as exc:
            raise DeepResearchError("structured data runtime returned an invalid row count") from exc
        if declared_count != len(rows):
            raise DeepResearchError("structured data row count did not match returned evidence")
        if task.required and not rows:
            raise DeepResearchError("required data task produced no admissible evidence")

        database = str(provenance.get("database") or "").strip()
        if not database:
            raise DeepResearchError("structured data provenance is missing the database identity")
        source_id = self._source_id(self.connector_id, database, spec.table)
        quality = self._bounded_score(provenance.get("quality_score"), default=0.9)
        freshness = self._bounded_score(provenance.get("freshness_score"), default=0.5)
        source = ResearchSource(
            source_id=source_id,
            title=f"DPN structured data: {spec.table}",
            url=f"dpn://connector/{self.connector_id}/{database}/{spec.table}",
            domain="local.dpn",
            source_type="structured_data",
            authority_score=quality,
            freshness_score=freshness,
            relevance_score=quality,
            quality_score=quality,
            metadata={
                "connector_id": self.connector_id,
                "provider": "sqlite",
                "database": database,
                "table": spec.table,
                "read_only": True,
                "parameterized": True,
            },
        )

        nodes: list[EvidenceNode] = []
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, dict):
                raise DeepResearchError("structured data row must be an object")
            canonical = self._canonical_row(raw_row)
            excerpt = canonical[: self.max_excerpt_chars]
            node = EvidenceNode(
                evidence_id=self._evidence_id(task.task_id, source_id, index, canonical),
                source_id=source_id,
                source_type="structured_data",
                title=f"{spec.table} row {index + 1}",
                locator=f"sqlite://{database}/{spec.table}#row-{index + 1}",
                excerpt=excerpt,
                quality_score=quality,
                freshness_score=freshness,
                metadata={
                    "task_id": task.task_id,
                    "workstream": task.workstream.value,
                    "connector_id": self.connector_id,
                    "database": database,
                    "table": spec.table,
                    "row_index": index,
                    "truncated": len(excerpt) < len(canonical),
                    "read_only": True,
                    "parameterized": True,
                },
            )
            node.validate()
            nodes.append(node)

        # Preflight all graph identities before any mutation so admission remains atomic.
        existing_sources = {item.source_id: item for item in graph.sources}
        existing_evidence = {item.evidence_id: item for item in graph.evidence}
        current_source = existing_sources.get(source.source_id)
        if current_source is not None and current_source != source:
            raise DeepResearchError("structured data source id collision detected before graph commit")
        for node in nodes:
            current_node = existing_evidence.get(node.evidence_id)
            if current_node is not None and current_node != node:
                raise DeepResearchError("structured data evidence id collision detected before graph commit")

        if nodes:
            graph.add_source(source)
            for node in nodes:
                graph.add_evidence(node)

        return DataWorkerResult(
            task_id=task.task_id,
            table=spec.table,
            row_count=len(rows),
            evidence_count=len(nodes),
            connector_id=self.connector_id,
        )


__all__ = ["DataQuerySpec", "DataWorkerResult", "DeepResearchDataWorker", "StructuredDataRuntimeProtocol"]
