from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Iterable

from app.research_intelligence import ClaimEvidence, ResearchIntelligence, ResearchSource


class DeepResearchError(ValueError):
    """Raised when deep-research evidence cannot be trusted or validated."""


class ResearchWorkstream(str, Enum):
    WEB = "web"
    DOCUMENTS = "documents"
    DATA = "data"


class ClaimStatus(str, Enum):
    VERIFIED = "verified"
    DISPUTED = "disputed"
    UNSUPPORTED = "unsupported"
    STALE = "stale"


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    workstream: ResearchWorkstream
    query: str
    purpose: str
    required: bool = True

    def validate(self) -> None:
        if not self.task_id.strip() or not self.query.strip() or not self.purpose.strip():
            raise DeepResearchError("research task id, query, and purpose are required")


@dataclass(frozen=True)
class ResearchPlan:
    objective: str
    tasks: tuple[ResearchTask, ...]

    def validate(self) -> None:
        if not self.objective.strip():
            raise DeepResearchError("research objective is required")
        if not self.tasks:
            raise DeepResearchError("research plan requires at least one task")
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise DeepResearchError("research task ids must be unique")
        for task in self.tasks:
            task.validate()


@dataclass(frozen=True)
class EvidenceNode:
    evidence_id: str
    source_id: str
    source_type: str
    title: str
    locator: str
    excerpt: str
    quality_score: float
    freshness_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.evidence_id.strip() or not self.source_id.strip():
            raise DeepResearchError("evidence id and source id are required")
        if not self.locator.strip():
            raise DeepResearchError("evidence locator is required")
        if not self.excerpt.strip():
            raise DeepResearchError("evidence excerpt is required")
        for value, name in ((self.quality_score, "quality_score"), (self.freshness_score, "freshness_score")):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise DeepResearchError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class ResearchClaim:
    claim_id: str
    text: str
    supporting_evidence_ids: tuple[str, ...] = ()
    refuting_evidence_ids: tuple[str, ...] = ()
    confidence: float = 0.5

    def validate(self) -> None:
        if not self.claim_id.strip() or not self.text.strip():
            raise DeepResearchError("claim id and text are required")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise DeepResearchError("claim confidence must be between 0 and 1")
        if set(self.supporting_evidence_ids) & set(self.refuting_evidence_ids):
            raise DeepResearchError("the same evidence cannot both support and refute a claim")


@dataclass(frozen=True)
class FactCheckResult:
    claim_id: str
    status: ClaimStatus
    confidence: float
    supporting_evidence_ids: tuple[str, ...]
    refuting_evidence_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class CitationReference:
    citation_id: str
    claim_id: str
    evidence_id: str


class ResearchDirector:
    """Deterministically decomposes a research objective into bounded workstreams."""

    def __init__(self, *, include_web: bool = True, include_documents: bool = True, include_data: bool = True) -> None:
        self.include_web = bool(include_web)
        self.include_documents = bool(include_documents)
        self.include_data = bool(include_data)

    @staticmethod
    def _normalize_objective(objective: str) -> str:
        return re.sub(r"\s+", " ", (objective or "").strip())

    def plan(self, objective: str) -> ResearchPlan:
        objective = self._normalize_objective(objective)
        if not objective:
            raise DeepResearchError("research objective is required")
        tasks: list[ResearchTask] = []
        if self.include_web:
            tasks.append(ResearchTask(
                task_id="web-primary",
                workstream=ResearchWorkstream.WEB,
                query=objective,
                purpose="Find current external sources, primary references, and independent corroboration.",
            ))
        if self.include_documents:
            tasks.append(ResearchTask(
                task_id="documents-primary",
                workstream=ResearchWorkstream.DOCUMENTS,
                query=objective,
                purpose="Inspect available documents and project evidence for directly relevant facts.",
                required=False,
            ))
        if self.include_data:
            tasks.append(ResearchTask(
                task_id="data-primary",
                workstream=ResearchWorkstream.DATA,
                query=objective,
                purpose="Inspect available structured data for quantitative or operational evidence.",
                required=False,
            ))
        plan = ResearchPlan(objective=objective, tasks=tuple(tasks))
        plan.validate()
        return plan


class EvidenceGraph:
    """Typed claim-to-source evidence graph with provenance-preserving admission rules."""

    def __init__(self) -> None:
        self._sources: dict[str, ResearchSource] = {}
        self._evidence: dict[str, EvidenceNode] = {}
        self._claims: dict[str, ResearchClaim] = {}

    @property
    def sources(self) -> tuple[ResearchSource, ...]:
        return tuple(sorted(self._sources.values(), key=lambda item: item.source_id))

    @property
    def evidence(self) -> tuple[EvidenceNode, ...]:
        return tuple(sorted(self._evidence.values(), key=lambda item: item.evidence_id))

    @property
    def claims(self) -> tuple[ResearchClaim, ...]:
        return tuple(sorted(self._claims.values(), key=lambda item: item.claim_id))

    def add_source(self, source: ResearchSource) -> None:
        if not source.source_id.strip() or not source.url.strip():
            raise DeepResearchError("research source requires source id and URL")
        existing = self._sources.get(source.source_id)
        if existing is not None and existing.url != source.url:
            raise DeepResearchError("source id collision detected")
        self._sources[source.source_id] = source

    def add_evidence(self, node: EvidenceNode) -> None:
        node.validate()
        if node.source_id not in self._sources:
            raise DeepResearchError("evidence references an unknown source")
        existing = self._evidence.get(node.evidence_id)
        if existing is not None and existing != node:
            raise DeepResearchError("evidence id collision detected")
        self._evidence[node.evidence_id] = node

    def add_claim(self, claim: ResearchClaim) -> None:
        claim.validate()
        referenced = set(claim.supporting_evidence_ids) | set(claim.refuting_evidence_ids)
        missing = sorted(referenced - set(self._evidence))
        if missing:
            raise DeepResearchError(f"claim references unknown evidence: {', '.join(missing)}")
        existing = self._claims.get(claim.claim_id)
        if existing is not None and existing != claim:
            raise DeepResearchError("claim id collision detected")
        self._claims[claim.claim_id] = claim

    def claim(self, claim_id: str) -> ResearchClaim | None:
        return self._claims.get(claim_id)

    def evidence_node(self, evidence_id: str) -> EvidenceNode | None:
        return self._evidence.get(evidence_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_count": len(self._sources),
            "evidence_count": len(self._evidence),
            "claim_count": len(self._claims),
            "sources": [
                {
                    "source_id": item.source_id,
                    "title": item.title,
                    "url": item.url,
                    "domain": item.domain,
                    "source_type": item.source_type,
                    "quality_score": item.quality_score,
                    "freshness_score": item.freshness_score,
                }
                for item in self.sources
            ],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "source_id": item.source_id,
                    "source_type": item.source_type,
                    "title": item.title,
                    "locator": item.locator,
                    "excerpt": item.excerpt,
                    "quality_score": item.quality_score,
                    "freshness_score": item.freshness_score,
                    "metadata": dict(item.metadata),
                }
                for item in self.evidence
            ],
            "claims": [
                {
                    "claim_id": item.claim_id,
                    "text": item.text,
                    "supporting_evidence_ids": list(item.supporting_evidence_ids),
                    "refuting_evidence_ids": list(item.refuting_evidence_ids),
                    "confidence": item.confidence,
                }
                for item in self.claims
            ],
        }


class ResearchFactChecker:
    """Deterministic claim verifier that never upgrades unsupported claims to verified."""

    def __init__(self, *, minimum_quality: float = 0.55, stale_freshness: float = 0.2) -> None:
        if not 0.0 <= minimum_quality <= 1.0:
            raise ValueError("minimum_quality must be between 0 and 1")
        if not 0.0 <= stale_freshness <= 1.0:
            raise ValueError("stale_freshness must be between 0 and 1")
        self.minimum_quality = minimum_quality
        self.stale_freshness = stale_freshness

    def check(self, graph: EvidenceGraph, claim_id: str) -> FactCheckResult:
        claim = graph.claim(claim_id)
        if claim is None:
            raise DeepResearchError("claim does not exist")

        supporting = [graph.evidence_node(item) for item in claim.supporting_evidence_ids]
        refuting = [graph.evidence_node(item) for item in claim.refuting_evidence_ids]
        supporting = [item for item in supporting if item is not None and item.quality_score >= self.minimum_quality]
        refuting = [item for item in refuting if item is not None and item.quality_score >= self.minimum_quality]

        if supporting and refuting:
            return FactCheckResult(
                claim_id=claim.claim_id,
                status=ClaimStatus.DISPUTED,
                confidence=min(1.0, max(claim.confidence, 0.7)),
                supporting_evidence_ids=tuple(item.evidence_id for item in supporting),
                refuting_evidence_ids=tuple(item.evidence_id for item in refuting),
                reason="qualified evidence exists on both sides of the claim",
            )
        if not supporting:
            return FactCheckResult(
                claim_id=claim.claim_id,
                status=ClaimStatus.UNSUPPORTED,
                confidence=0.0,
                supporting_evidence_ids=(),
                refuting_evidence_ids=tuple(item.evidence_id for item in refuting),
                reason="no qualified supporting evidence was admitted",
            )
        if all(item.freshness_score <= self.stale_freshness for item in supporting):
            return FactCheckResult(
                claim_id=claim.claim_id,
                status=ClaimStatus.STALE,
                confidence=min(claim.confidence, 0.6),
                supporting_evidence_ids=tuple(item.evidence_id for item in supporting),
                refuting_evidence_ids=(),
                reason="all qualified supporting evidence is stale",
            )
        return FactCheckResult(
            claim_id=claim.claim_id,
            status=ClaimStatus.VERIFIED,
            confidence=min(1.0, max(claim.confidence, sum(item.quality_score for item in supporting) / len(supporting))),
            supporting_evidence_ids=tuple(item.evidence_id for item in supporting),
            refuting_evidence_ids=(),
            reason="qualified supporting evidence is present without qualified refutation",
        )

    def check_all(self, graph: EvidenceGraph) -> tuple[FactCheckResult, ...]:
        return tuple(self.check(graph, claim.claim_id) for claim in graph.claims)


class ResearchConflictDetector:
    """Maps graph claims into the mature deterministic conflict detector."""

    @staticmethod
    def detect(graph: EvidenceGraph) -> list[dict[str, Any]]:
        evidence: list[ClaimEvidence] = []
        for claim in graph.claims:
            if claim.supporting_evidence_ids:
                evidence.append(ClaimEvidence(
                    claim=claim.text,
                    stance="supports",
                    source_ids=claim.supporting_evidence_ids,
                    confidence=claim.confidence,
                ))
            if claim.refuting_evidence_ids:
                evidence.append(ClaimEvidence(
                    claim=claim.text,
                    stance="refutes",
                    source_ids=claim.refuting_evidence_ids,
                    confidence=claim.confidence,
                ))
        return ResearchIntelligence.detect_conflicts(evidence)


class CitationValidator:
    """Rejects citations that do not map a known claim to evidence actually attached to it."""

    def validate(self, graph: EvidenceGraph, citations: Iterable[CitationReference]) -> dict[str, Any]:
        accepted: list[dict[str, str]] = []
        rejected: list[dict[str, str]] = []
        seen: set[str] = set()

        for citation in citations:
            if not citation.citation_id.strip() or citation.citation_id in seen:
                rejected.append({"citation_id": citation.citation_id, "reason": "invalid_or_duplicate_citation_id"})
                continue
            seen.add(citation.citation_id)
            claim = graph.claim(citation.claim_id)
            node = graph.evidence_node(citation.evidence_id)
            if claim is None:
                rejected.append({"citation_id": citation.citation_id, "reason": "unknown_claim"})
                continue
            if node is None:
                rejected.append({"citation_id": citation.citation_id, "reason": "unknown_evidence"})
                continue
            if citation.evidence_id not in set(claim.supporting_evidence_ids) | set(claim.refuting_evidence_ids):
                rejected.append({"citation_id": citation.citation_id, "reason": "evidence_not_attached_to_claim"})
                continue
            accepted.append({
                "citation_id": citation.citation_id,
                "claim_id": citation.claim_id,
                "evidence_id": citation.evidence_id,
                "source_id": node.source_id,
                "locator": node.locator,
            })

        return {
            "ok": not rejected,
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": accepted,
            "rejected": rejected,
        }


class DeepResearchReadinessGate:
    """Final deterministic gate for evidence-backed research synthesis."""

    def __init__(self, fact_checker: ResearchFactChecker | None = None) -> None:
        self.fact_checker = fact_checker or ResearchFactChecker()

    def evaluate(self, graph: EvidenceGraph) -> dict[str, Any]:
        checks = self.fact_checker.check_all(graph)
        conflicts = ResearchConflictDetector.detect(graph)
        verified = [item for item in checks if item.status == ClaimStatus.VERIFIED]
        blocked = [item for item in checks if item.status != ClaimStatus.VERIFIED]
        return {
            "ready": bool(graph.claims) and not blocked and not conflicts,
            "claim_count": len(graph.claims),
            "verified_count": len(verified),
            "blocked_count": len(blocked),
            "conflict_count": len(conflicts),
            "claims": [
                {
                    "claim_id": item.claim_id,
                    "status": item.status.value,
                    "confidence": item.confidence,
                    "reason": item.reason,
                }
                for item in checks
            ],
            "conflicts": conflicts,
        }


__all__ = [
    "CitationReference",
    "CitationValidator",
    "ClaimStatus",
    "DeepResearchError",
    "DeepResearchReadinessGate",
    "EvidenceGraph",
    "EvidenceNode",
    "FactCheckResult",
    "ResearchClaim",
    "ResearchConflictDetector",
    "ResearchDirector",
    "ResearchFactChecker",
    "ResearchPlan",
    "ResearchTask",
    "ResearchWorkstream",
]
