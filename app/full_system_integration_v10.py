from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Iterable


class IntegrationError(ValueError):
    """Raised when full-system integration evidence is incomplete or unsafe."""


class IntegrationState(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SubsystemEvidence:
    subsystem_id: str
    batch: int
    state: IntegrationState
    release_gate: str
    evidence_digest: str
    approval_boundary_preserved: bool
    external_side_effects_performed: bool = False
    detail: str = ""

    def normalized(self) -> "SubsystemEvidence":
        subsystem_id = self.subsystem_id.strip().lower()
        release_gate = self.release_gate.strip()
        digest = self.evidence_digest.strip().lower()
        detail = self.detail.strip()
        if not subsystem_id:
            raise IntegrationError("subsystem_id is required")
        if isinstance(self.batch, bool) or not isinstance(self.batch, int) or not 1 <= self.batch <= 18:
            raise IntegrationError("batch must be an integer between 1 and 18")
        if not release_gate:
            raise IntegrationError("release_gate is required")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise IntegrationError("evidence_digest must be a lowercase SHA-256 hex digest")
        if self.external_side_effects_performed:
            raise IntegrationError("integration readiness evidence must not perform external side effects")
        return SubsystemEvidence(
            subsystem_id=subsystem_id,
            batch=self.batch,
            state=IntegrationState(self.state),
            release_gate=release_gate,
            evidence_digest=digest,
            approval_boundary_preserved=bool(self.approval_boundary_preserved),
            external_side_effects_performed=False,
            detail=detail,
        )


@dataclass(frozen=True)
class IntegrationReadiness:
    schema_version: int
    checkpoint: str
    ready: bool
    required_subsystems: tuple[str, ...]
    admitted_subsystems: tuple[str, ...]
    blocked_subsystems: tuple[str, ...]
    missing_subsystems: tuple[str, ...]
    approval_boundary_failures: tuple[str, ...]
    evidence: tuple[SubsystemEvidence, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "required_subsystems": list(self.required_subsystems),
            "admitted_subsystems": list(self.admitted_subsystems),
            "blocked_subsystems": list(self.blocked_subsystems),
            "missing_subsystems": list(self.missing_subsystems),
            "approval_boundary_failures": list(self.approval_boundary_failures),
            "evidence": [asdict(item) for item in self.evidence],
        }


REQUIRED_V10_SUBSYSTEMS = (
    "model_intelligence",
    "benchmark_laboratory",
    "autonomous_coding",
    "computer_browser_agent",
    "multimodal_runtime",
    "long_horizon_missions",
    "connector_protocol",
    "deep_research",
    "layered_memory",
    "artifact_studio",
    "voice_runtime",
    "proactive_intelligence",
    "specialist_agents",
    "capability_marketplace",
    "self_improvement",
)


class FullSystemIntegrationGate:
    """Evidence-only Batch 15 integration gate.

    This gate does not invoke providers, tools, connectors, plugins, repository writes,
    deployments, approvals, or external actions. It only admits already-produced
    subsystem release evidence and fails closed on missing, duplicate, blocked, or
    approval-boundary-violating components.
    """

    def __init__(self, required_subsystems: Iterable[str] = REQUIRED_V10_SUBSYSTEMS) -> None:
        required = tuple(sorted({str(item).strip().lower() for item in required_subsystems if str(item).strip()}))
        if not required:
            raise IntegrationError("at least one required subsystem is required")
        self.required_subsystems = required

    def evaluate(self, evidence: Iterable[SubsystemEvidence]) -> IntegrationReadiness:
        admitted: dict[str, SubsystemEvidence] = {}
        for raw in evidence:
            item = raw.normalized()
            if item.subsystem_id in admitted:
                raise IntegrationError(f"duplicate subsystem evidence: {item.subsystem_id}")
            admitted[item.subsystem_id] = item

        required = set(self.required_subsystems)
        unexpected = sorted(set(admitted) - required)
        if unexpected:
            raise IntegrationError(f"unexpected subsystem evidence: {', '.join(unexpected)}")

        missing = tuple(sorted(required - set(admitted)))
        blocked = tuple(sorted(
            subsystem_id
            for subsystem_id, item in admitted.items()
            if item.state is not IntegrationState.READY
        ))
        approval_failures = tuple(sorted(
            subsystem_id
            for subsystem_id, item in admitted.items()
            if not item.approval_boundary_preserved
        ))
        admitted_ids = tuple(sorted(admitted))
        ready = not missing and not blocked and not approval_failures and admitted_ids == self.required_subsystems
        reason = (
            "all required v10 subsystem release evidence is ready and approval boundaries are preserved"
            if ready
            else "full-system integration remains blocked"
        )
        return IntegrationReadiness(
            schema_version=1,
            checkpoint="v10.0.0-batch-15",
            ready=ready,
            required_subsystems=self.required_subsystems,
            admitted_subsystems=admitted_ids,
            blocked_subsystems=blocked,
            missing_subsystems=missing,
            approval_boundary_failures=approval_failures,
            evidence=tuple(admitted[key] for key in admitted_ids),
            reason=reason,
        )


__all__ = [
    "FullSystemIntegrationGate",
    "IntegrationError",
    "IntegrationReadiness",
    "IntegrationState",
    "REQUIRED_V10_SUBSYSTEMS",
    "SubsystemEvidence",
]
