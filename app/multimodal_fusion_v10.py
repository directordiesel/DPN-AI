from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.unified_multimodal_runtime_v10 import (
    EvidenceKind,
    Modality,
    MultimodalAsset,
    MultimodalEvidence,
    MultimodalRequest,
    MultimodalRuntimeError,
    MultimodalSession,
    RouteDecision,
)


class FusionError(MultimodalRuntimeError):
    """Raised when multimodal evidence cannot be safely fused."""


class ClaimStatus(str, Enum):
    SUPPORTED = "supported"
    CONFLICTED = "conflicted"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class ProvenanceRef:
    asset_id: str
    source_ref: str
    page: int | None = None
    frame: int | None = None
    timestamp_ms: int | None = None
    evidence_id: str = ""

    def validate(self) -> None:
        if not self.asset_id.strip():
            raise FusionError("provenance asset id is required")
        if not self.source_ref.strip():
            raise FusionError("provenance source ref is required")
        if self.page is not None and self.page < 1:
            raise FusionError("provenance page must be >= 1")
        if self.frame is not None and self.frame < 0:
            raise FusionError("provenance frame must be >= 0")
        if self.timestamp_ms is not None and self.timestamp_ms < 0:
            raise FusionError("provenance timestamp must be non-negative")


@dataclass(frozen=True)
class FusedClaim:
    claim_id: str
    statement: str
    status: ClaimStatus
    confidence: float
    provenance: tuple[ProvenanceRef, ...]
    conflicts: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.claim_id.strip():
            raise FusionError("claim id is required")
        if not self.statement.strip():
            raise FusionError("claim statement is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise FusionError("claim confidence must be between 0 and 1")
        if not self.provenance:
            raise FusionError("fused claims require provenance")
        for ref in self.provenance:
            ref.validate()
        if self.status == ClaimStatus.CONFLICTED and not self.conflicts:
            raise FusionError("conflicted claims require conflict details")


@dataclass(frozen=True)
class EvidenceConflict:
    asset_id: str
    evidence_ids: tuple[str, ...]
    reason: str

    def validate(self) -> None:
        if not self.asset_id.strip():
            raise FusionError("conflict asset id is required")
        if len(self.evidence_ids) < 2:
            raise FusionError("conflict requires at least two evidence ids")
        if not self.reason.strip():
            raise FusionError("conflict reason is required")


@dataclass(frozen=True)
class FusionContext:
    request_id: str
    route_provider: str
    route_model: str
    claims: tuple[FusedClaim, ...]
    conflicts: tuple[EvidenceConflict, ...]
    source_count: int
    evidence_count: int
    verified: bool
    reason: str


class MultimodalConflictDetector:
    """Deterministic conflict checks that do not invent semantic equivalence.

    The detector only flags explicit contradictions that can be established from
    structured evidence metadata/content supplied to the runtime. Deeper semantic
    contradiction analysis belongs to a capable reasoning provider and must be
    recorded as provider-backed evidence before becoming trusted context.
    """

    @staticmethod
    def detect(session: MultimodalSession, asset_ids: Iterable[str]) -> tuple[EvidenceConflict, ...]:
        wanted = set(asset_ids)
        conflicts: list[EvidenceConflict] = []
        by_asset: dict[str, list[MultimodalEvidence]] = {}
        for item in session.evidence:
            if item.asset_id in wanted:
                by_asset.setdefault(item.asset_id, []).append(item)

        for asset_id, items in sorted(by_asset.items()):
            exact_groups: dict[EvidenceKind, dict[str, list[str]]] = {}
            for item in items:
                normalized = " ".join(item.content.split()).strip().casefold()
                if not normalized:
                    continue
                exact_groups.setdefault(item.kind, {}).setdefault(normalized, []).append(item.evidence_id)

            for kind, values in exact_groups.items():
                if kind not in {EvidenceKind.METADATA, EvidenceKind.TABLE, EvidenceKind.STRUCTURE}:
                    continue
                if len(values) <= 1:
                    continue
                evidence_ids = tuple(sorted(eid for group in values.values() for eid in group))
                conflicts.append(
                    EvidenceConflict(
                        asset_id=asset_id,
                        evidence_ids=evidence_ids,
                        reason=f"multiple incompatible {kind.value} evidence values were recorded for the same asset",
                    )
                )
        return tuple(conflicts)


class MultimodalFusionEngine:
    @staticmethod
    def _provenance(session: MultimodalSession, evidence: MultimodalEvidence) -> ProvenanceRef:
        asset = session.assets[evidence.asset_id]
        return ProvenanceRef(
            asset_id=asset.asset_id,
            source_ref=asset.source_ref,
            page=asset.page,
            frame=asset.frame,
            timestamp_ms=asset.timestamp_ms,
            evidence_id=evidence.evidence_id,
        )

    @classmethod
    def build_context(
        cls,
        session: MultimodalSession,
        request: MultimodalRequest,
        *,
        route: RouteDecision,
        cross_checked: bool,
        uncertainty_reported: bool,
    ) -> FusionContext:
        session.validate()
        request.validate()
        missing = [asset_id for asset_id in request.asset_ids if asset_id not in session.assets]
        if missing:
            raise FusionError(f"cannot fuse missing assets: {', '.join(missing)}")
        if not route.provider_id.strip() or not route.model.strip():
            raise FusionError("fusion requires a concrete route provider and model")

        relevant = [item for item in session.evidence if item.asset_id in request.asset_ids]
        if not relevant:
            raise FusionError("fusion requires concrete evidence")
        evidenced = {item.asset_id for item in relevant}
        if evidenced != set(request.asset_ids):
            raise FusionError("every requested asset must contribute evidence before fusion")

        conflicts = MultimodalConflictDetector.detect(session, request.asset_ids)
        conflict_ids = {eid for conflict in conflicts for eid in conflict.evidence_ids}

        claims: list[FusedClaim] = []
        for index, item in enumerate(relevant, start=1):
            item.validate()
            provider_backed = bool(item.provider.strip() and item.model.strip())
            confidence = item.confidence if item.confidence is not None else (0.9 if provider_backed else 0.8)
            status = ClaimStatus.CONFLICTED if item.evidence_id in conflict_ids else ClaimStatus.SUPPORTED
            claim_conflicts = tuple(
                conflict.reason for conflict in conflicts if item.evidence_id in conflict.evidence_ids
            )
            claims.append(
                FusedClaim(
                    claim_id=f"claim-{index}",
                    statement=item.content.strip(),
                    status=status,
                    confidence=confidence,
                    provenance=(cls._provenance(session, item),),
                    conflicts=claim_conflicts,
                )
            )

        visual_assets = {
            asset_id
            for asset_id in request.asset_ids
            if session.assets[asset_id].modality in {Modality.IMAGE, Modality.SCREENSHOT, Modality.VIDEO}
        }
        visual_evidence = [
            item for item in relevant if item.asset_id in visual_assets and item.kind == EvidenceKind.VISUAL
        ]
        if visual_assets and not visual_evidence:
            return FusionContext(
                request_id=request.request_id,
                route_provider=route.provider_id,
                route_model=route.model,
                claims=tuple(claims),
                conflicts=conflicts,
                source_count=len(request.asset_ids),
                evidence_count=len(relevant),
                verified=False,
                reason="visual assets are present but no provider-backed visual evidence was recorded",
            )
        if visual_evidence and any(not item.provider.strip() or not item.model.strip() for item in visual_evidence):
            return FusionContext(
                request_id=request.request_id,
                route_provider=route.provider_id,
                route_model=route.model,
                claims=tuple(claims),
                conflicts=conflicts,
                source_count=len(request.asset_ids),
                evidence_count=len(relevant),
                verified=False,
                reason="visual evidence requires actual provider and model provenance",
            )
        if request.require_cross_check and not cross_checked:
            return FusionContext(
                request_id=request.request_id,
                route_provider=route.provider_id,
                route_model=route.model,
                claims=tuple(claims),
                conflicts=conflicts,
                source_count=len(request.asset_ids),
                evidence_count=len(relevant),
                verified=False,
                reason="request requires cross-check evidence",
            )
        if not uncertainty_reported:
            return FusionContext(
                request_id=request.request_id,
                route_provider=route.provider_id,
                route_model=route.model,
                claims=tuple(claims),
                conflicts=conflicts,
                source_count=len(request.asset_ids),
                evidence_count=len(relevant),
                verified=False,
                reason="uncertainty must be explicitly reported",
            )
        if conflicts:
            return FusionContext(
                request_id=request.request_id,
                route_provider=route.provider_id,
                route_model=route.model,
                claims=tuple(claims),
                conflicts=conflicts,
                source_count=len(request.asset_ids),
                evidence_count=len(relevant),
                verified=False,
                reason="evidence conflicts must be resolved or explicitly adjudicated before verified completion",
            )
        return FusionContext(
            request_id=request.request_id,
            route_provider=route.provider_id,
            route_model=route.model,
            claims=tuple(claims),
            conflicts=(),
            source_count=len(request.asset_ids),
            evidence_count=len(relevant),
            verified=True,
            reason="multimodal evidence fused with provenance and verification gates satisfied",
        )


__all__ = [
    "ClaimStatus",
    "EvidenceConflict",
    "FusedClaim",
    "FusionContext",
    "FusionError",
    "MultimodalConflictDetector",
    "MultimodalFusionEngine",
    "ProvenanceRef",
]
