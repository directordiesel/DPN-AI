from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Protocol, Sequence

from app.deep_research_engine_v10 import (
    CitationReference,
    CitationValidator,
    DeepResearchError,
    DeepResearchReadinessGate,
    EvidenceGraph,
    ResearchClaim,
    ResearchConflictDetector,
    ResearchFactChecker,
)


class ClaimExtractorProtocol(Protocol):
    async def extract_claims(self, objective: str, evidence: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]: ...


@dataclass(frozen=True)
class ClaimOrchestrationResult:
    objective: str
    claim_count: int
    workstreams_used: tuple[str, ...]
    fact_checks: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    citation_validation: dict[str, Any]
    readiness: dict[str, Any]


class DeepResearchClaimOrchestrator:
    """Admits extractor-proposed claims only when every evidence relationship is already proven by the graph."""

    def __init__(
        self,
        extractor: ClaimExtractorProtocol,
        *,
        max_claims: int = 64,
        max_claim_chars: int = 2_000,
        fact_checker: ResearchFactChecker | None = None,
    ) -> None:
        if not 1 <= max_claims <= 256:
            raise ValueError("max_claims must be between 1 and 256")
        if not 32 <= max_claim_chars <= 8_000:
            raise ValueError("max_claim_chars must be between 32 and 8000")
        self.extractor = extractor
        self.max_claims = max_claims
        self.max_claim_chars = max_claim_chars
        self.fact_checker = fact_checker or ResearchFactChecker()
        self.citation_validator = CitationValidator()
        self.readiness_gate = DeepResearchReadinessGate(self.fact_checker)

    @staticmethod
    def _evidence_payload(graph: EvidenceGraph) -> tuple[dict[str, Any], ...]:
        payload: list[dict[str, Any]] = []
        for node in graph.evidence:
            payload.append(
                {
                    "evidence_id": node.evidence_id,
                    "source_id": node.source_id,
                    "source_type": node.source_type,
                    "title": node.title,
                    "locator": node.locator,
                    "excerpt": node.excerpt,
                    "quality_score": node.quality_score,
                    "freshness_score": node.freshness_score,
                    "workstream": str(node.metadata.get("workstream") or "").strip(),
                }
            )
        return tuple(payload)

    def _parse_candidate(self, raw: dict[str, Any], known_evidence: set[str]) -> ResearchClaim:
        if not isinstance(raw, dict):
            raise DeepResearchError("claim extractor result must contain objects")
        claim_id = str(raw.get("claim_id") or "").strip()
        text = " ".join(str(raw.get("text") or "").split())
        if len(text) > self.max_claim_chars:
            raise DeepResearchError("extracted claim exceeds maximum length")

        supporting_raw = raw.get("supporting_evidence_ids", [])
        refuting_raw = raw.get("refuting_evidence_ids", [])
        if not isinstance(supporting_raw, (list, tuple)) or not isinstance(refuting_raw, (list, tuple)):
            raise DeepResearchError("claim evidence references must be lists")
        supporting = tuple(str(item).strip() for item in supporting_raw if str(item).strip())
        refuting = tuple(str(item).strip() for item in refuting_raw if str(item).strip())
        if len(supporting) != len(set(supporting)) or len(refuting) != len(set(refuting)):
            raise DeepResearchError("claim contains duplicate evidence references")
        if not supporting and not refuting:
            raise DeepResearchError("extracted claims require attached evidence")

        referenced = set(supporting) | set(refuting)
        missing = sorted(referenced - known_evidence)
        if missing:
            raise DeepResearchError(f"claim extractor referenced unknown evidence: {', '.join(missing)}")

        try:
            confidence = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError) as exc:
            raise DeepResearchError("claim confidence must be numeric") from exc
        if not math.isfinite(confidence):
            raise DeepResearchError("claim confidence must be finite")

        claim = ResearchClaim(
            claim_id=claim_id,
            text=text,
            supporting_evidence_ids=supporting,
            refuting_evidence_ids=refuting,
            confidence=confidence,
        )
        claim.validate()
        return claim

    async def extract_and_assess(
        self,
        objective: str,
        graph: EvidenceGraph,
        *,
        require_mixed_workstreams: bool = False,
    ) -> ClaimOrchestrationResult:
        objective = " ".join((objective or "").split())
        if not objective:
            raise DeepResearchError("research objective is required")
        evidence_payload = self._evidence_payload(graph)
        if not evidence_payload:
            raise DeepResearchError("claim extraction requires admitted evidence")

        raw_candidates = await self.extractor.extract_claims(objective, evidence_payload)
        if not isinstance(raw_candidates, (list, tuple)):
            raise DeepResearchError("claim extractor must return a bounded sequence")
        if not raw_candidates:
            raise DeepResearchError("claim extractor returned no claims")
        if len(raw_candidates) > self.max_claims:
            raise DeepResearchError("claim extractor exceeded maximum claim count")

        known_evidence = {item.evidence_id for item in graph.evidence}
        staged = [self._parse_candidate(raw, known_evidence) for raw in raw_candidates]
        ids = [item.claim_id for item in staged]
        if len(ids) != len(set(ids)):
            raise DeepResearchError("claim extractor returned duplicate claim ids")

        existing = {item.claim_id: item for item in graph.claims}
        for claim in staged:
            current = existing.get(claim.claim_id)
            if current is not None and current != claim:
                raise DeepResearchError("claim id collision detected before graph commit")

        referenced_ids = {
            evidence_id
            for claim in staged
            for evidence_id in (*claim.supporting_evidence_ids, *claim.refuting_evidence_ids)
        }
        workstreams = tuple(
            sorted(
                {
                    str(graph.evidence_node(evidence_id).metadata.get("workstream") or "").strip()
                    for evidence_id in referenced_ids
                    if graph.evidence_node(evidence_id) is not None
                    and str(graph.evidence_node(evidence_id).metadata.get("workstream") or "").strip()
                }
            )
        )
        if require_mixed_workstreams and len(workstreams) < 2:
            raise DeepResearchError("mixed-workstream research requires evidence from at least two workstreams")

        # Commit only after all candidates, references, collisions, and workstream requirements pass.
        for claim in staged:
            graph.add_claim(claim)

        checks = self.fact_checker.check_all(graph)
        conflicts = ResearchConflictDetector.detect(graph)
        citations: list[CitationReference] = []
        for claim in staged:
            for evidence_id in claim.supporting_evidence_ids:
                citations.append(
                    CitationReference(
                        citation_id=f"cite:{claim.claim_id}:{evidence_id}",
                        claim_id=claim.claim_id,
                        evidence_id=evidence_id,
                    )
                )
        citation_validation = self.citation_validator.validate(graph, citations)
        readiness = self.readiness_gate.evaluate(graph)
        if not citation_validation.get("ok"):
            readiness = dict(readiness)
            readiness["ready"] = False
            readiness["citation_validation_ok"] = False
        else:
            readiness = dict(readiness)
            readiness["citation_validation_ok"] = True

        return ClaimOrchestrationResult(
            objective=objective,
            claim_count=len(staged),
            workstreams_used=workstreams,
            fact_checks=tuple(
                {
                    "claim_id": item.claim_id,
                    "status": item.status.value,
                    "confidence": item.confidence,
                    "supporting_evidence_ids": list(item.supporting_evidence_ids),
                    "refuting_evidence_ids": list(item.refuting_evidence_ids),
                    "reason": item.reason,
                }
                for item in checks
            ),
            conflicts=tuple(dict(item) for item in conflicts),
            citation_validation=citation_validation,
            readiness=readiness,
        )


__all__ = ["ClaimExtractorProtocol", "ClaimOrchestrationResult", "DeepResearchClaimOrchestrator"]
