from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from app.deep_research_engine_v10 import (
    CitationReference,
    CitationValidator,
    ClaimStatus,
    DeepResearchError,
    EvidenceGraph,
    ResearchConflictDetector,
    ResearchFactChecker,
)


class ResearchWriterProtocol(Protocol):
    async def write(self, objective: str, claims: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DeepResearchWriteResult:
    status: str
    objective: str
    report: str
    sections: tuple[dict[str, Any], ...]
    citation_count: int
    unresolved_conflicts: tuple[dict[str, Any], ...]
    blocked_claims: tuple[dict[str, Any], ...]


class DeepResearchWriter:
    """Synthesizes only verified claims and appends citations from trusted graph relationships."""

    def __init__(self, writer: ResearchWriterProtocol, *, max_sections: int = 24, max_section_chars: int = 8_000) -> None:
        if not 1 <= max_sections <= 64:
            raise ValueError("max_sections must be between 1 and 64")
        if not 128 <= max_section_chars <= 32_000:
            raise ValueError("max_section_chars must be between 128 and 32000")
        self.writer = writer
        self.max_sections = max_sections
        self.max_section_chars = max_section_chars
        self.fact_checker = ResearchFactChecker()
        self.citation_validator = CitationValidator()

    @staticmethod
    def _normalized(value: Any) -> str:
        return " ".join(str(value or "").split())

    def _assessment(self, graph: EvidenceGraph) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "claim_id": item.claim_id,
                "status": item.status.value,
                "confidence": item.confidence,
                "supporting_evidence_ids": tuple(item.supporting_evidence_ids),
                "refuting_evidence_ids": tuple(item.refuting_evidence_ids),
                "reason": item.reason,
            }
            for item in self.fact_checker.check_all(graph)
        )

    @staticmethod
    def _conflict_payload(graph: EvidenceGraph, checks: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        detector_conflicts = tuple(dict(item) for item in ResearchConflictDetector.detect(graph))
        disputed = tuple(
            {
                "claim_id": item["claim_id"],
                "status": item["status"],
                "reason": item["reason"],
                "supporting_evidence_ids": list(item["supporting_evidence_ids"]),
                "refuting_evidence_ids": list(item["refuting_evidence_ids"]),
            }
            for item in checks
            if item["status"] == ClaimStatus.DISPUTED.value
        )
        return detector_conflicts + disputed

    def _writer_claims(self, graph: EvidenceGraph, checks: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        verified = {item["claim_id"]: item for item in checks if item["status"] == ClaimStatus.VERIFIED.value}
        payload: list[dict[str, Any]] = []
        for claim in graph.claims:
            check = verified.get(claim.claim_id)
            if check is None:
                continue
            evidence = []
            for evidence_id in check["supporting_evidence_ids"]:
                node = graph.evidence_node(evidence_id)
                if node is None:
                    raise DeepResearchError("verified claim references missing evidence")
                evidence.append(
                    {
                        "evidence_id": node.evidence_id,
                        "source_id": node.source_id,
                        "title": node.title,
                        "locator": node.locator,
                        "excerpt": node.excerpt,
                        "workstream": str(node.metadata.get("workstream") or "").strip(),
                    }
                )
            payload.append(
                {
                    "claim_id": claim.claim_id,
                    "text": claim.text,
                    "confidence": check["confidence"],
                    "evidence": evidence,
                }
            )
        return tuple(payload)

    def _validated_citations(self, graph: EvidenceGraph, claim_ids: Sequence[str]) -> tuple[dict[str, str], ...]:
        citations: list[CitationReference] = []
        for claim_id in claim_ids:
            claim = graph.claim(claim_id)
            if claim is None:
                raise DeepResearchError("writer referenced unknown claim")
            for evidence_id in claim.supporting_evidence_ids:
                citations.append(
                    CitationReference(
                        citation_id=f"cite:{claim_id}:{evidence_id}",
                        claim_id=claim_id,
                        evidence_id=evidence_id,
                    )
                )
        result = self.citation_validator.validate(graph, citations)
        if not result.get("ok"):
            raise DeepResearchError("trusted citation validation failed during synthesis")
        return tuple(dict(item) for item in result.get("accepted", []))

    async def synthesize(self, objective: str, graph: EvidenceGraph) -> DeepResearchWriteResult:
        objective = self._normalized(objective)
        if not objective:
            raise DeepResearchError("research objective is required")
        if not graph.claims:
            raise DeepResearchError("research synthesis requires admitted claims")

        checks = self._assessment(graph)
        blocked = tuple(item for item in checks if item["status"] != ClaimStatus.VERIFIED.value)
        conflicts = self._conflict_payload(graph, checks)
        if blocked or conflicts:
            return DeepResearchWriteResult(
                status="blocked",
                objective=objective,
                report="",
                sections=(),
                citation_count=0,
                unresolved_conflicts=conflicts,
                blocked_claims=blocked,
            )

        claims = self._writer_claims(graph, checks)
        raw = await self.writer.write(objective, claims)
        if not isinstance(raw, dict):
            raise DeepResearchError("research writer must return an object")
        raw_sections = raw.get("sections")
        if not isinstance(raw_sections, (list, tuple)) or not raw_sections:
            raise DeepResearchError("research writer must return non-empty sections")
        if len(raw_sections) > self.max_sections:
            raise DeepResearchError("research writer exceeded maximum section count")

        known_claims = {item["claim_id"] for item in claims}
        staged: list[dict[str, Any]] = []
        cited_claims: set[str] = set()
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                raise DeepResearchError("research writer sections must be objects")
            title = self._normalized(raw_section.get("title"))
            text = self._normalized(raw_section.get("text"))
            claim_ids_raw = raw_section.get("claim_ids")
            if not title or not text:
                raise DeepResearchError("research writer sections require title and text")
            if len(text) > self.max_section_chars:
                raise DeepResearchError("research writer section exceeds maximum length")
            if not isinstance(claim_ids_raw, (list, tuple)):
                raise DeepResearchError("research writer section claim_ids must be a list")
            claim_ids = tuple(self._normalized(item) for item in claim_ids_raw if self._normalized(item))
            if not claim_ids or len(claim_ids) != len(set(claim_ids)):
                raise DeepResearchError("research writer sections require unique grounded claim ids")
            unknown = sorted(set(claim_ids) - known_claims)
            if unknown:
                raise DeepResearchError(f"research writer referenced unverified claims: {', '.join(unknown)}")
            citations = self._validated_citations(graph, claim_ids)
            if not citations:
                raise DeepResearchError("research writer section has no accepted citations")
            cited_claims.update(claim_ids)
            staged.append({"title": title, "text": text, "claim_ids": list(claim_ids), "citations": list(citations)})

        missing = sorted(known_claims - cited_claims)
        if missing:
            raise DeepResearchError(f"research writer omitted verified claims: {', '.join(missing)}")

        report_parts: list[str] = []
        citation_count = 0
        for section in staged:
            markers = []
            for citation in section["citations"]:
                markers.append(f"[{citation['citation_id']}]")
            citation_count += len(markers)
            report_parts.append(f"## {section['title']}\n\n{section['text']} {' '.join(markers)}")

        return DeepResearchWriteResult(
            status="ready",
            objective=objective,
            report="\n\n".join(report_parts),
            sections=tuple(staged),
            citation_count=citation_count,
            unresolved_conflicts=(),
            blocked_claims=(),
        )


__all__ = ["DeepResearchWriteResult", "DeepResearchWriter", "ResearchWriterProtocol"]
