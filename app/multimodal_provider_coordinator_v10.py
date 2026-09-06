from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from app.multimodal_fusion_v10 import FusionContext, MultimodalFusionEngine
from app.unified_multimodal_runtime_v10 import (
    EvidenceKind,
    Modality,
    MultimodalAsset,
    MultimodalCapabilityPlanner,
    MultimodalEvidence,
    MultimodalEvidenceGate,
    MultimodalReadiness,
    MultimodalRequest,
    MultimodalRouter,
    MultimodalRuntimeError,
    MultimodalSession,
    ProviderProfile,
    RouteDecision,
)


class ProviderExecutionError(MultimodalRuntimeError):
    """Raised when multimodal provider execution cannot be trusted."""


VisionRunner = Callable[[MultimodalAsset, str, str], Awaitable[dict[str, Any]]]
TranscriptionRunner = Callable[[MultimodalAsset, str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ProviderExecutionResult:
    asset_id: str
    evidence_ids: tuple[str, ...]
    provider: str
    model: str
    success: bool
    reason: str


@dataclass(frozen=True)
class MultimodalExecutionResult:
    route: RouteDecision
    provider_results: tuple[ProviderExecutionResult, ...]
    readiness: MultimodalReadiness
    fusion: FusionContext


class MultimodalProviderCoordinator:
    """End-to-end Batch 4 provider execution coordinator.

    Provider calls are fail-closed and transactionally staged. A failed later call
    cannot leave partial provider evidence in the session. Provider/model identity
    must be reported by the backend itself and must match the selected route; silent
    model/provider fallback is rejected rather than being mislabeled as routed work.
    """

    def __init__(
        self,
        profiles: Iterable[ProviderProfile],
        *,
        vision_runner: VisionRunner | None = None,
        transcription_runner: TranscriptionRunner | None = None,
    ) -> None:
        self.profiles = tuple(profiles)
        if not self.profiles:
            raise ProviderExecutionError("at least one provider profile is required")
        for profile in self.profiles:
            profile.validate()
        self.vision_runner = vision_runner
        self.transcription_runner = transcription_runner

    @staticmethod
    def _next_evidence_id(
        session: MultimodalSession,
        staged: Iterable[MultimodalEvidence],
        asset_id: str,
        kind: EvidenceKind,
    ) -> str:
        prefix = f"{asset_id}:{kind.value}:"
        existing = sum(1 for item in session.evidence if item.evidence_id.startswith(prefix))
        pending = sum(1 for item in staged if item.evidence_id.startswith(prefix))
        return f"{prefix}{existing + pending + 1}"

    @staticmethod
    def _provider_fields(payload: dict[str, Any], route: RouteDecision) -> tuple[str, str]:
        provider = str(payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not provider or not model:
            raise ProviderExecutionError("provider execution must explicitly report provider and model provenance")
        if provider != route.provider_id or model != route.model:
            raise ProviderExecutionError(
                "provider execution provenance does not match the selected route; silent fallback is not allowed"
            )
        return provider, model

    @staticmethod
    def _existing_route_evidence(
        session: MultimodalSession,
        asset_id: str,
        kind: EvidenceKind,
        route: RouteDecision,
    ) -> tuple[MultimodalEvidence, ...]:
        return tuple(
            item
            for item in session.evidence
            if item.asset_id == asset_id
            and item.kind == kind
            and item.provider == route.provider_id
            and item.model == route.model
        )

    async def _build_vision_evidence(
        self,
        session: MultimodalSession,
        staged: list[MultimodalEvidence],
        asset: MultimodalAsset,
        route: RouteDecision,
        objective: str,
    ) -> tuple[ProviderExecutionResult, MultimodalEvidence | None]:
        existing = self._existing_route_evidence(session, asset.asset_id, EvidenceKind.VISUAL, route)
        if existing:
            return (
                ProviderExecutionResult(
                    asset.asset_id,
                    tuple(item.evidence_id for item in existing),
                    route.provider_id,
                    route.model,
                    True,
                    "existing provider-backed vision evidence reused",
                ),
                None,
            )
        if self.vision_runner is None:
            raise ProviderExecutionError("vision evidence is required but no vision runner is configured")
        payload = await self.vision_runner(asset, objective, route.model)
        if not isinstance(payload, dict) or not payload.get("ok"):
            reason = str((payload or {}).get("error") if isinstance(payload, dict) else "vision runner returned invalid payload")
            raise ProviderExecutionError(reason or "vision provider failed")
        content = str(payload.get("analysis") or payload.get("content") or "").strip()
        if not content:
            raise ProviderExecutionError("vision provider returned no evidence content")
        provider, model = self._provider_fields(payload, route)
        confidence = float(payload["confidence"]) if payload.get("confidence") is not None else None
        evidence = MultimodalEvidence(
            evidence_id=self._next_evidence_id(session, staged, asset.asset_id, EvidenceKind.VISUAL),
            asset_id=asset.asset_id,
            kind=EvidenceKind.VISUAL,
            content=content,
            provider=provider,
            model=model,
            confidence=confidence,
        )
        evidence.validate()
        return (
            ProviderExecutionResult(asset.asset_id, (evidence.evidence_id,), provider, model, True, "vision evidence staged"),
            evidence,
        )

    async def _build_transcript_evidence(
        self,
        session: MultimodalSession,
        staged: list[MultimodalEvidence],
        asset: MultimodalAsset,
        route: RouteDecision,
    ) -> tuple[ProviderExecutionResult, MultimodalEvidence | None]:
        existing = self._existing_route_evidence(session, asset.asset_id, EvidenceKind.TRANSCRIPT, route)
        if existing:
            return (
                ProviderExecutionResult(
                    asset.asset_id,
                    tuple(item.evidence_id for item in existing),
                    route.provider_id,
                    route.model,
                    True,
                    "existing provider-backed transcript evidence reused",
                ),
                None,
            )
        if self.transcription_runner is None:
            raise ProviderExecutionError("transcription evidence is required but no transcription runner is configured")
        payload = await self.transcription_runner(asset, route.model)
        if not isinstance(payload, dict) or not payload.get("ok"):
            reason = str((payload or {}).get("error") if isinstance(payload, dict) else "transcription runner returned invalid payload")
            raise ProviderExecutionError(reason or "transcription provider failed")
        content = str(payload.get("transcript") or payload.get("content") or "").strip()
        if not content:
            raise ProviderExecutionError("transcription provider returned no transcript")
        provider, model = self._provider_fields(payload, route)
        confidence = float(payload["confidence"]) if payload.get("confidence") is not None else None
        evidence = MultimodalEvidence(
            evidence_id=self._next_evidence_id(session, staged, asset.asset_id, EvidenceKind.TRANSCRIPT),
            asset_id=asset.asset_id,
            kind=EvidenceKind.TRANSCRIPT,
            content=content,
            provider=provider,
            model=model,
            confidence=confidence,
        )
        evidence.validate()
        return (
            ProviderExecutionResult(asset.asset_id, (evidence.evidence_id,), provider, model, True, "transcript evidence staged"),
            evidence,
        )

    async def execute(
        self,
        session: MultimodalSession,
        request: MultimodalRequest,
        *,
        cross_checked: bool,
        uncertainty_reported: bool,
    ) -> MultimodalExecutionResult:
        session.validate()
        request.validate()
        assets: list[MultimodalAsset] = []
        for asset_id in request.asset_ids:
            asset = session.assets.get(asset_id)
            if asset is None:
                raise ProviderExecutionError(f"requested asset is missing: {asset_id}")
            assets.append(asset)

        required = MultimodalCapabilityPlanner.required_for_assets(assets)
        route = MultimodalRouter.select(self.profiles, required, local_only=request.local_only)
        results: list[ProviderExecutionResult] = []
        staged: list[MultimodalEvidence] = []

        for asset in assets:
            needs_visual = asset.modality in {Modality.IMAGE, Modality.SCREENSHOT, Modality.VIDEO}
            if asset.modality in {Modality.PDF, Modality.DOCUMENT, Modality.PRESENTATION} and not asset.native_text.strip():
                needs_visual = True
            if needs_visual:
                result, evidence = await self._build_vision_evidence(session, staged, asset, route, request.objective)
                results.append(result)
                if evidence is not None:
                    staged.append(evidence)

            needs_transcription = asset.modality == Modality.AUDIO and not asset.native_text.strip()
            if needs_transcription:
                result, evidence = await self._build_transcript_evidence(session, staged, asset, route)
                results.append(result)
                if evidence is not None:
                    staged.append(evidence)

        # Commit provider evidence only after every required call succeeds.
        for evidence in staged:
            session.add_evidence(evidence)

        readiness = MultimodalEvidenceGate.evaluate(
            session,
            request,
            route=route,
            cross_checked=cross_checked,
            uncertainty_reported=uncertainty_reported,
        )
        fusion = MultimodalFusionEngine.build_context(
            session,
            request,
            route=route,
            cross_checked=cross_checked,
            uncertainty_reported=uncertainty_reported,
        )
        return MultimodalExecutionResult(route, tuple(results), readiness, fusion)


__all__ = [
    "MultimodalExecutionResult",
    "MultimodalProviderCoordinator",
    "ProviderExecutionError",
    "ProviderExecutionResult",
    "TranscriptionRunner",
    "VisionRunner",
]
