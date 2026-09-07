from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from app.advanced_layered_memory_v10 import (
    AdvancedLayeredMemory,
    KnowledgeClass,
    MemoryContext,
    MemoryLayer,
    MemoryProvenance,
    MemoryWriteRequest,
)
from app.deep_research_engine_v10 import ClaimStatus, EvidenceGraph
from app.deep_research_mission_v10 import DeepResearchMissionResult


@dataclass(frozen=True)
class ResearchMemoryIngestionResult:
    ok: bool
    release_ready: bool
    semantic_attempted: int
    semantic_stored: int
    episode_stored: bool
    memory_ids: tuple[str, ...]
    errors: tuple[dict[str, str], ...]


class DeepResearchMemoryBridge:
    """Promotes trusted Deep Research output into v10 episodic/semantic memory.

    Only mission output that is release-ready, citation-valid, and backed by
    VERIFIED fact checks can enter durable semantic memory. The bridge derives
    all evidence identities from the trusted EvidenceGraph rather than model
    output and stores the mission episode only after every semantic promotion
    succeeds. Existing memory version/conflict rules remain authoritative.
    """

    MAX_VERIFIED_CLAIMS = 128
    MAX_REPORT_CHARS = 20_000

    def __init__(self, memory: AdvancedLayeredMemory) -> None:
        self.memory = memory

    @staticmethod
    def _clean(value: str | None) -> str:
        return " ".join((value or "").split())

    @staticmethod
    def _stable_key(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:20]
        return f"{prefix}:{digest}"

    @staticmethod
    def _fact_checks(result: DeepResearchMissionResult) -> list[dict[str, Any]]:
        raw = result.claim_assessment.get("fact_checks")
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def _preflight(
        self,
        result: DeepResearchMissionResult,
        graph: EvidenceGraph,
    ) -> tuple[list[tuple[Any, tuple[str, ...], float]], str | None]:
        readiness = dict(result.release_readiness or {})
        citation_validation = dict(result.claim_assessment.get("citation_validation") or {})
        if result.status != "ready" or not bool(readiness.get("release_ready")):
            return [], "research mission is not release-ready"
        if not bool(citation_validation.get("ok")):
            return [], "research mission citations are not valid"

        fact_checks = self._fact_checks(result)
        if not fact_checks:
            return [], "research mission has no fact-check evidence"
        if len(fact_checks) > self.MAX_VERIFIED_CLAIMS:
            return [], "research mission exceeds semantic promotion claim limit"

        staged: list[tuple[Any, tuple[str, ...], float]] = []
        seen_claims: set[str] = set()
        for check in fact_checks:
            claim_id = self._clean(str(check.get("claim_id") or ""))
            status = self._clean(str(check.get("status") or "")).lower()
            if not claim_id or claim_id in seen_claims:
                return [], "research fact checks contain an invalid or duplicate claim id"
            seen_claims.add(claim_id)
            if status != ClaimStatus.VERIFIED.value:
                return [], f"research claim {claim_id} is not verified"

            claim = graph.claim(claim_id)
            if claim is None:
                return [], f"research claim {claim_id} is absent from the trusted evidence graph"
            evidence_ids = tuple(str(item).strip() for item in claim.supporting_evidence_ids if str(item).strip())
            if not evidence_ids:
                return [], f"research claim {claim_id} has no supporting evidence"
            if tuple(sorted(set(evidence_ids))) != tuple(sorted(evidence_ids)):
                return [], f"research claim {claim_id} has duplicate supporting evidence"

            nodes = [graph.evidence_node(item) for item in evidence_ids]
            if any(node is None for node in nodes):
                return [], f"research claim {claim_id} references missing evidence"
            qualified_nodes = [node for node in nodes if node is not None]
            authority = sum(node.quality_score for node in qualified_nodes) / len(qualified_nodes)
            confidence = float(check.get("confidence", claim.confidence))
            if not 0.0 <= confidence <= 1.0:
                return [], f"research claim {claim_id} has invalid fact-check confidence"
            staged.append((claim, evidence_ids, max(0.0, min(authority, 1.0))))

        graph_claim_ids = {claim.claim_id for claim in graph.claims}
        if seen_claims != graph_claim_ids:
            return [], "fact-check set does not exactly cover the trusted graph claims"
        return staged, None

    async def ingest(
        self,
        result: DeepResearchMissionResult,
        graph: EvidenceGraph,
        *,
        context: MemoryContext,
        sensitive: bool = False,
    ) -> ResearchMemoryIngestionResult:
        staged, error = self._preflight(result, graph)
        if error is not None:
            return ResearchMemoryIngestionResult(
                ok=False,
                release_ready=False,
                semantic_attempted=0,
                semantic_stored=0,
                episode_stored=False,
                memory_ids=(),
                errors=({"stage": "preflight", "error": error},),
            )

        memory_ids: list[str] = []
        errors: list[dict[str, str]] = []
        semantic_stored = 0
        objective = self._clean(result.objective)
        mission_key = self._stable_key("research-mission", objective)

        for claim, evidence_ids, authority in staged:
            request = MemoryWriteRequest(
                layer=MemoryLayer.SEMANTIC,
                key=self._stable_key("research-claim", objective, claim.claim_id),
                content=self._clean(claim.text),
                knowledge_class=KnowledgeClass.FACT,
                provenance=MemoryProvenance(
                    source_type="deep_research",
                    source_id=mission_key,
                    evidence_ids=evidence_ids,
                    confidence=float(claim.confidence),
                    authority=authority,
                ),
                context=context,
                sensitive=sensitive,
            )
            receipt = await self.memory.remember(request)
            if not receipt.get("ok") or not receipt.get("stored"):
                errors.append({
                    "stage": "semantic",
                    "claim_id": claim.claim_id,
                    "error": self._clean(str(receipt.get("error") or "semantic memory write failed")),
                })
                break
            semantic_stored += 1
            if receipt.get("memory_id"):
                memory_ids.append(str(receipt["memory_id"]))

        if errors or semantic_stored != len(staged):
            return ResearchMemoryIngestionResult(
                ok=False,
                release_ready=True,
                semantic_attempted=len(staged),
                semantic_stored=semantic_stored,
                episode_stored=False,
                memory_ids=tuple(memory_ids),
                errors=tuple(errors),
            )

        report = self._clean(str(result.synthesis.get("report") or ""))
        if not report:
            return ResearchMemoryIngestionResult(
                ok=False,
                release_ready=True,
                semantic_attempted=len(staged),
                semantic_stored=semantic_stored,
                episode_stored=False,
                memory_ids=tuple(memory_ids),
                errors=({"stage": "episode", "error": "release-ready mission has no synthesis report"},),
            )
        report = report[: self.MAX_REPORT_CHARS]
        all_evidence_ids = tuple(sorted({item for _, evidence_ids, _ in staged for item in evidence_ids}))
        episode_request = MemoryWriteRequest(
            layer=MemoryLayer.EPISODIC,
            key=mission_key,
            content=f"Objective: {objective}\nReport: {report}",
            knowledge_class=KnowledgeClass.EPISODE,
            provenance=MemoryProvenance(
                source_type="deep_research_mission",
                source_id=mission_key,
                evidence_ids=all_evidence_ids,
                confidence=1.0,
                authority=sum(authority for _, _, authority in staged) / len(staged),
            ),
            context=context,
            sensitive=sensitive,
        )
        episode_receipt = await self.memory.remember(episode_request)
        if not episode_receipt.get("ok") or not episode_receipt.get("stored"):
            return ResearchMemoryIngestionResult(
                ok=False,
                release_ready=True,
                semantic_attempted=len(staged),
                semantic_stored=semantic_stored,
                episode_stored=False,
                memory_ids=tuple(memory_ids),
                errors=({
                    "stage": "episode",
                    "error": self._clean(str(episode_receipt.get("error") or "episodic memory write failed")),
                },),
            )
        if episode_receipt.get("memory_id"):
            memory_ids.append(str(episode_receipt["memory_id"]))

        return ResearchMemoryIngestionResult(
            ok=True,
            release_ready=True,
            semantic_attempted=len(staged),
            semantic_stored=semantic_stored,
            episode_stored=True,
            memory_ids=tuple(memory_ids),
            errors=(),
        )


__all__ = ["DeepResearchMemoryBridge", "ResearchMemoryIngestionResult"]
