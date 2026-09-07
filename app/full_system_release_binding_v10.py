from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Mapping

from app.full_system_integration_v10 import IntegrationError, IntegrationState, SubsystemEvidence


@dataclass(frozen=True)
class ReleaseBindingSpec:
    subsystem_id: str
    batch: int
    expected_checkpoint: str
    approval_boundary_required: bool = True


BATCH_RELEASE_BINDINGS = (
    ReleaseBindingSpec("layered_memory", 8, "v10.0.0-batch-8"),
    ReleaseBindingSpec("artifact_studio", 9, "v10.0.0-batch-9"),
    ReleaseBindingSpec("voice_runtime", 10, "v10.0.0-batch-10"),
    ReleaseBindingSpec("proactive_intelligence", 11, "v10.0.0-batch-11"),
    ReleaseBindingSpec("specialist_agents", 12, "v10.0.0-batch-12"),
    ReleaseBindingSpec("capability_marketplace", 13, "v10.0.0-batch-13"),
    ReleaseBindingSpec("self_improvement", 14, "v10.0.0-batch-14"),
)


class FullSystemReleaseBinder:
    """Converts trusted batch release payloads into Batch 15 subsystem evidence.

    The binder performs no tests, tools, providers, connector calls, writes, approvals,
    or deployments. It only validates already-produced release payloads and hashes the
    canonical payload so the integration gate can bind to exact evidence.
    """

    def __init__(self, specs: Iterable[ReleaseBindingSpec] = BATCH_RELEASE_BINDINGS) -> None:
        self._specs = {spec.subsystem_id: spec for spec in specs}
        if len(self._specs) != len(tuple(specs)):
            raise IntegrationError("duplicate release binding subsystem")

    @staticmethod
    def _digest(payload: Mapping) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def bind(self, subsystem_id: str, payload: Mapping) -> SubsystemEvidence:
        subsystem_id = subsystem_id.strip().lower()
        spec = self._specs.get(subsystem_id)
        if spec is None:
            raise IntegrationError(f"no trusted release binding for {subsystem_id}")
        if not isinstance(payload, Mapping):
            raise IntegrationError("release payload must be a mapping")
        if payload.get("schema_version") != 1:
            raise IntegrationError("release payload schema_version must be 1")
        if payload.get("checkpoint") != spec.expected_checkpoint:
            raise IntegrationError("release payload checkpoint mismatch")
        if payload.get("ready") is not True:
            raise IntegrationError("release payload is not ready")
        if payload.get("execution_authorized") is True:
            raise IntegrationError("release readiness cannot grant execution authorization")
        if payload.get("external_side_effects_performed") is True:
            raise IntegrationError("release readiness cannot report external side effects")
        return SubsystemEvidence(
            subsystem_id=subsystem_id,
            batch=spec.batch,
            state=IntegrationState.READY,
            release_gate=spec.expected_checkpoint,
            evidence_digest=self._digest(dict(payload)),
            approval_boundary_preserved=spec.approval_boundary_required,
            external_side_effects_performed=False,
            detail="bound to canonical trusted batch release payload",
        )

    def bind_all(self, payloads: Mapping[str, Mapping]) -> tuple[SubsystemEvidence, ...]:
        unknown = sorted(set(payloads) - set(self._specs))
        if unknown:
            raise IntegrationError(f"unexpected release payloads: {', '.join(unknown)}")
        missing = sorted(set(self._specs) - set(payloads))
        if missing:
            raise IntegrationError(f"missing release payloads: {', '.join(missing)}")
        return tuple(self.bind(key, payloads[key]) for key in sorted(self._specs))


__all__ = ["BATCH_RELEASE_BINDINGS", "FullSystemReleaseBinder", "ReleaseBindingSpec"]
