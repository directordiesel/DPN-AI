from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from app.full_system_integration_v10 import FullSystemIntegrationGate, IntegrationReadiness, IntegrationState, SubsystemEvidence
from app.full_system_release_binding_v10 import FullSystemReleaseBinder


@dataclass(frozen=True)
class VerifiedMergeAttestation:
    subsystem_id: str
    batch: int
    commit_sha: str
    approval_boundary_preserved: bool = True


EARLY_BATCH_ATTESTATIONS = (
    VerifiedMergeAttestation("model_intelligence", 1, "2978e3eb087fb000b7d04450bb3dc14d5c56b5b2"),
    VerifiedMergeAttestation("benchmark_laboratory", 1, "2978e3eb087fb000b7d04450bb3dc14d5c56b5b2"),
    VerifiedMergeAttestation("autonomous_coding", 2, "47312f3b11cace3e6b35f0757e32d72847054364"),
    VerifiedMergeAttestation("computer_browser_agent", 3, "279f739379aaf7c4eb12da6cf3da29d002f2ba3c"),
    VerifiedMergeAttestation("multimodal_runtime", 4, "c5c3d3d832a38adc4a3f9d4a72f1e56de3809b9a"),
    VerifiedMergeAttestation("long_horizon_missions", 5, "0a6821f8388a763c8ea360d068e70300a9b522b0"),
    VerifiedMergeAttestation("connector_protocol", 6, "b2627a57de9b18ede9e7b54a1cf05b9720e1ae28"),
    VerifiedMergeAttestation("deep_research", 7, "a07008b6818804a595568fa73e1a753b06c654cb"),
)


def _attestation_digest(attestation: VerifiedMergeAttestation) -> str:
    payload = {
        "subsystem_id": attestation.subsystem_id,
        "batch": attestation.batch,
        "commit_sha": attestation.commit_sha,
        "approval_boundary_preserved": attestation.approval_boundary_preserved,
        "source": "verified_merged_checkpoint",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def early_batch_evidence() -> tuple[SubsystemEvidence, ...]:
    evidence: list[SubsystemEvidence] = []
    for item in EARLY_BATCH_ATTESTATIONS:
        if len(item.commit_sha) != 40 or any(ch not in "0123456789abcdef" for ch in item.commit_sha):
            raise ValueError(f"invalid verified merge SHA for {item.subsystem_id}")
        evidence.append(
            SubsystemEvidence(
                subsystem_id=item.subsystem_id,
                batch=item.batch,
                state=IntegrationState.READY,
                release_gate=f"verified-merged-checkpoint:{item.commit_sha}",
                evidence_digest=_attestation_digest(item),
                approval_boundary_preserved=item.approval_boundary_preserved,
                external_side_effects_performed=False,
                detail="historical exact-head CI/security/runtime verified merged checkpoint",
            )
        )
    return tuple(evidence)


def evaluate_full_system_acceptance(release_payloads: Mapping[str, Mapping]) -> IntegrationReadiness:
    late_evidence = FullSystemReleaseBinder().bind_all(release_payloads)
    return FullSystemIntegrationGate().evaluate((*early_batch_evidence(), *late_evidence))


__all__ = [
    "EARLY_BATCH_ATTESTATIONS",
    "VerifiedMergeAttestation",
    "early_batch_evidence",
    "evaluate_full_system_acceptance",
]
