from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class MultimodalRuntimeError(ValueError):
    """Raised when multimodal input or provider evidence violates the v10 contract."""


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    SCREENSHOT = "screenshot"
    PDF = "pdf"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    CODE = "code"
    AUDIO = "audio"
    VIDEO = "video"
    TRANSCRIPT = "transcript"


class EvidenceKind(str, Enum):
    NATIVE_TEXT = "native_text"
    VISUAL = "visual"
    STRUCTURE = "structure"
    METADATA = "metadata"
    TRANSCRIPT = "transcript"
    TEMPORAL = "temporal"
    CODE = "code"
    TABLE = "table"


class ProviderCapability(str, Enum):
    TEXT_REASONING = "text_reasoning"
    VISION = "vision"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT_TEXT = "document_text"
    DOCUMENT_VISION = "document_vision"
    SPREADSHEET = "spreadsheet"
    CODE = "code"
    TRANSCRIPTION = "transcription"


@dataclass(frozen=True)
class MultimodalAsset:
    asset_id: str
    modality: Modality
    source_ref: str
    sha256: str = ""
    mime_type: str = ""
    page: int | None = None
    frame: int | None = None
    timestamp_ms: int | None = None
    native_text: str = ""

    def validate(self) -> None:
        if not self.asset_id.strip():
            raise MultimodalRuntimeError("asset id is required")
        if not self.source_ref.strip():
            raise MultimodalRuntimeError("asset source reference is required")
        if self.page is not None and self.page < 1:
            raise MultimodalRuntimeError("page must be >= 1")
        if self.frame is not None and self.frame < 0:
            raise MultimodalRuntimeError("frame must be >= 0")
        if self.timestamp_ms is not None and self.timestamp_ms < 0:
            raise MultimodalRuntimeError("timestamp must be non-negative")


@dataclass(frozen=True)
class MultimodalEvidence:
    evidence_id: str
    asset_id: str
    kind: EvidenceKind
    content: str
    provider: str = ""
    model: str = ""
    confidence: float | None = None

    def validate(self) -> None:
        if not self.evidence_id.strip():
            raise MultimodalRuntimeError("evidence id is required")
        if not self.asset_id.strip():
            raise MultimodalRuntimeError("evidence asset id is required")
        if not self.content.strip():
            raise MultimodalRuntimeError("evidence content is required")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise MultimodalRuntimeError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    model: str
    capabilities: tuple[ProviderCapability, ...]
    configured: bool = True
    healthy: bool = True
    local: bool = False

    def validate(self) -> None:
        if not self.provider_id.strip():
            raise MultimodalRuntimeError("provider id is required")
        if not self.model.strip():
            raise MultimodalRuntimeError("provider model is required")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise MultimodalRuntimeError("provider capabilities must be unique")

    def supports_all(self, required: Iterable[ProviderCapability]) -> bool:
        available = set(self.capabilities)
        return set(required).issubset(available)


@dataclass(frozen=True)
class MultimodalRequest:
    request_id: str
    objective: str
    asset_ids: tuple[str, ...]
    require_cross_check: bool = True
    local_only: bool = False

    def validate(self) -> None:
        if not self.request_id.strip():
            raise MultimodalRuntimeError("request id is required")
        if not self.objective.strip():
            raise MultimodalRuntimeError("request objective is required")
        if not self.asset_ids:
            raise MultimodalRuntimeError("at least one asset is required")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise MultimodalRuntimeError("request asset ids must be unique")


@dataclass(frozen=True)
class RouteDecision:
    provider_id: str
    model: str
    required_capabilities: tuple[ProviderCapability, ...]
    reason: str


@dataclass(frozen=True)
class MultimodalReadiness:
    ready: bool
    missing_capabilities: tuple[ProviderCapability, ...] = ()
    reason: str = ""


@dataclass
class MultimodalSession:
    session_id: str
    assets: dict[str, MultimodalAsset] = field(default_factory=dict)
    evidence: list[MultimodalEvidence] = field(default_factory=list)

    def validate(self) -> None:
        if not self.session_id.strip():
            raise MultimodalRuntimeError("session id is required")

    def add_asset(self, asset: MultimodalAsset) -> None:
        self.validate()
        asset.validate()
        if asset.asset_id in self.assets:
            raise MultimodalRuntimeError(f"duplicate asset id: {asset.asset_id}")
        self.assets[asset.asset_id] = asset

    def add_evidence(self, evidence: MultimodalEvidence) -> None:
        self.validate()
        evidence.validate()
        if evidence.asset_id not in self.assets:
            raise MultimodalRuntimeError("evidence references unknown asset")
        if any(item.evidence_id == evidence.evidence_id for item in self.evidence):
            raise MultimodalRuntimeError(f"duplicate evidence id: {evidence.evidence_id}")
        self.evidence.append(evidence)


class MultimodalCapabilityPlanner:
    _requirements = {
        Modality.TEXT: {ProviderCapability.TEXT_REASONING},
        Modality.IMAGE: {ProviderCapability.VISION},
        Modality.SCREENSHOT: {ProviderCapability.VISION},
        Modality.PDF: {ProviderCapability.DOCUMENT_TEXT},
        Modality.DOCUMENT: {ProviderCapability.DOCUMENT_TEXT},
        Modality.SPREADSHEET: {ProviderCapability.SPREADSHEET},
        Modality.PRESENTATION: {ProviderCapability.DOCUMENT_TEXT},
        Modality.CODE: {ProviderCapability.CODE},
        Modality.AUDIO: {ProviderCapability.AUDIO},
        Modality.VIDEO: {ProviderCapability.VIDEO},
        Modality.TRANSCRIPT: {ProviderCapability.TEXT_REASONING},
    }

    @classmethod
    def required_for_assets(cls, assets: Iterable[MultimodalAsset]) -> tuple[ProviderCapability, ...]:
        required: set[ProviderCapability] = set()
        materialized = list(assets)
        if not materialized:
            raise MultimodalRuntimeError("cannot plan multimodal capabilities without assets")
        for asset in materialized:
            asset.validate()
            required.update(cls._requirements[asset.modality])
            if asset.modality in {Modality.PDF, Modality.DOCUMENT, Modality.PRESENTATION} and not asset.native_text.strip():
                required.add(ProviderCapability.DOCUMENT_VISION)
            if asset.modality == Modality.AUDIO and not asset.native_text.strip():
                required.add(ProviderCapability.TRANSCRIPTION)
            if asset.modality == Modality.VIDEO:
                required.add(ProviderCapability.VISION)
        return tuple(sorted(required, key=lambda item: item.value))


class MultimodalRouter:
    @staticmethod
    def readiness(
        profiles: Iterable[ProviderProfile],
        required: Iterable[ProviderCapability],
        *,
        local_only: bool = False,
    ) -> MultimodalReadiness:
        materialized_required = tuple(required)
        candidates = []
        for profile in profiles:
            profile.validate()
            if not profile.configured or not profile.healthy:
                continue
            if local_only and not profile.local:
                continue
            candidates.append(profile)
        if not candidates:
            return MultimodalReadiness(False, materialized_required, "no configured healthy provider satisfies routing policy")
        if any(profile.supports_all(materialized_required) for profile in candidates):
            return MultimodalReadiness(True, (), "at least one provider satisfies all required capabilities")
        covered: set[ProviderCapability] = set()
        for profile in candidates:
            covered.update(profile.capabilities)
        missing = tuple(item for item in materialized_required if item not in covered)
        return MultimodalReadiness(False, missing or materialized_required, "no single provider satisfies the full multimodal request")

    @staticmethod
    def select(
        profiles: Iterable[ProviderProfile],
        required: Iterable[ProviderCapability],
        *,
        local_only: bool = False,
    ) -> RouteDecision:
        materialized_required = tuple(required)
        candidates = []
        for profile in profiles:
            profile.validate()
            if not profile.configured or not profile.healthy:
                continue
            if local_only and not profile.local:
                continue
            if profile.supports_all(materialized_required):
                candidates.append(profile)
        if not candidates:
            raise MultimodalRuntimeError("no configured healthy provider satisfies all required multimodal capabilities")
        candidates.sort(key=lambda profile: (not profile.local, profile.provider_id, profile.model))
        selected = candidates[0]
        return RouteDecision(
            provider_id=selected.provider_id,
            model=selected.model,
            required_capabilities=materialized_required,
            reason="selected provider satisfies every required modality capability without silent degradation",
        )


class MultimodalEvidenceGate:
    @staticmethod
    def evaluate(
        session: MultimodalSession,
        request: MultimodalRequest,
        *,
        route: RouteDecision,
        cross_checked: bool,
        uncertainty_reported: bool,
    ) -> MultimodalReadiness:
        session.validate()
        request.validate()
        missing_assets = [asset_id for asset_id in request.asset_ids if asset_id not in session.assets]
        if missing_assets:
            return MultimodalReadiness(False, (), f"missing requested assets: {', '.join(missing_assets)}")
        relevant = [item for item in session.evidence if item.asset_id in request.asset_ids]
        if not relevant:
            return MultimodalReadiness(False, (), "no concrete evidence has been recorded for the request")
        evidenced_assets = {item.asset_id for item in relevant}
        if evidenced_assets != set(request.asset_ids):
            return MultimodalReadiness(False, (), "every requested asset must contribute concrete evidence")
        provider_evidence = [item for item in relevant if item.provider and item.model]
        visual_assets = {
            asset_id
            for asset_id in request.asset_ids
            if session.assets[asset_id].modality in {Modality.IMAGE, Modality.SCREENSHOT, Modality.VIDEO}
        }
        if visual_assets and not any(item.kind == EvidenceKind.VISUAL and item.asset_id in visual_assets for item in relevant):
            return MultimodalReadiness(False, (), "visual assets require actual visual evidence")
        if visual_assets and not provider_evidence:
            return MultimodalReadiness(False, (), "visual reasoning requires recorded provider and model evidence")
        if request.require_cross_check and not cross_checked:
            return MultimodalReadiness(False, (), "multimodal request requires cross-check evidence")
        if not uncertainty_reported:
            return MultimodalReadiness(False, (), "uncertainty must be explicitly reported")
        if not route.provider_id.strip() or not route.model.strip():
            return MultimodalReadiness(False, (), "actual route provider and model must be recorded")
        return MultimodalReadiness(True, (), "multimodal evidence gates passed")


__all__ = [
    "EvidenceKind",
    "Modality",
    "MultimodalAsset",
    "MultimodalCapabilityPlanner",
    "MultimodalEvidence",
    "MultimodalEvidenceGate",
    "MultimodalReadiness",
    "MultimodalRequest",
    "MultimodalRouter",
    "MultimodalRuntimeError",
    "MultimodalSession",
    "ProviderCapability",
    "ProviderProfile",
    "RouteDecision",
]
