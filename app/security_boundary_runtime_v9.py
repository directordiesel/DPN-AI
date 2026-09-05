from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.persistence_security import sanitize_for_persistence
from app.security_hardening_v9 import (
    AuditEnvelope,
    InjectionAssessment,
    NetworkAuthorization,
    SecurityHardeningRuntime,
)


@dataclass(frozen=True)
class BoundaryAssessment:
    safe_payload: Any
    injection: InjectionAssessment
    network: NetworkAuthorization | None
    requires_approval: bool
    blocked: bool
    reasons: tuple[str, ...]


class SecurityBoundaryRuntime:
    """Compose v9 hardening checks at external-data and tool boundaries.

    The runtime is deliberately side-effect free. Existing callers remain
    responsible for SecretVault resolution, approval creation/execution, and
    persistence. This object only provides deterministic preflight evidence.
    """

    def __init__(self, *, integrity_key: bytes | None = None) -> None:
        self.integrity_key = integrity_key

    def assess_external_payload(
        self,
        payload: Any,
        *,
        text: str = "",
        network_url: str = "",
        allow_external_network: bool = False,
        allow_private_network: bool = False,
        allowed_hosts: Iterable[str] = (),
        write_like: bool = False,
        destructive: bool = False,
    ) -> BoundaryAssessment:
        SecurityHardeningRuntime.assert_no_plaintext_secrets(payload)
        safe_payload = sanitize_for_persistence(payload)
        injection = SecurityHardeningRuntime.assess_untrusted_text(text)
        network = None
        reasons: list[str] = list(injection.reasons)
        blocked = False

        if network_url:
            network = SecurityHardeningRuntime.authorize_network_url(
                network_url,
                allow_external=allow_external_network,
                allow_private=allow_private_network,
                allowed_hosts=allowed_hosts,
            )
            if not network.allowed:
                blocked = True
                reasons.append(network.reason)

        requires_approval = bool(write_like or destructive or injection.requires_isolation)
        if destructive:
            reasons.append("destructive operation requires explicit approval")
        elif write_like:
            reasons.append("write-like operation requires approval policy evaluation")
        if injection.requires_isolation:
            reasons.append("untrusted instructions require isolation from authority-bearing prompts")

        return BoundaryAssessment(
            safe_payload=safe_payload,
            injection=injection,
            network=network,
            requires_approval=requires_approval,
            blocked=blocked,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def audit_event(
        self,
        *,
        sequence: int,
        event_type: str,
        actor: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
        previous_hash: str = "",
    ) -> AuditEnvelope:
        return SecurityHardeningRuntime.build_audit_envelope(
            sequence=sequence,
            event_type=event_type,
            actor=actor,
            summary=summary,
            metadata=metadata,
            previous_hash=previous_hash,
            integrity_key=self.integrity_key,
        )

    def verify_audit(self, envelopes: Iterable[AuditEnvelope]) -> bool:
        return SecurityHardeningRuntime.verify_audit_chain(envelopes, integrity_key=self.integrity_key)


__all__ = ["BoundaryAssessment", "SecurityBoundaryRuntime"]
