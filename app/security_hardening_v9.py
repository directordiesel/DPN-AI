from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable
from urllib.parse import urlparse

from app.persistence_security import sanitize_for_persistence


class SecurityHardeningError(ValueError):
    """Raised when a v9 hardening boundary rejects an unsafe request."""


class InjectionRisk(str, Enum):
    NONE = "none"
    SUSPICIOUS = "suspicious"
    HIGH = "high"


@dataclass(frozen=True)
class InjectionAssessment:
    risk: InjectionRisk
    reasons: tuple[str, ...]
    requires_isolation: bool


@dataclass(frozen=True)
class NetworkAuthorization:
    allowed: bool
    reason: str
    host: str
    scheme: str


@dataclass(frozen=True)
class AuditEnvelope:
    sequence: int
    event_type: str
    actor: str
    summary: str
    metadata: dict[str, Any]
    previous_hash: str
    event_hash: str


_SECRET_KEY_PATTERN = re.compile(
    r"(?:^|[_\-.])(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|authorization|cookie|private[_-]?key)(?:$|[_\-.])",
    re.IGNORECASE,
)

_INJECTION_RULES: tuple[tuple[re.Pattern[str], str, InjectionRisk], ...] = (
    (re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|system|developer)\s+(?:instructions?|messages?)\b", re.I), "instruction override attempt", InjectionRisk.HIGH),
    (re.compile(r"\b(?:reveal|show|print|dump|expose)\b.{0,80}\b(?:system prompt|developer message|hidden prompt|secret|api key|token)\b", re.I | re.S), "protected-data extraction attempt", InjectionRisk.HIGH),
    (re.compile(r"\b(?:disable|bypass|circumvent)\b.{0,80}\b(?:approval|permission|sandbox|security|policy|guardrail)\b", re.I | re.S), "security-control bypass attempt", InjectionRisk.HIGH),
    (re.compile(r"\bact\s+as\b.{0,80}\b(?:system|administrator|root|developer)\b", re.I | re.S), "privilege-role manipulation", InjectionRisk.SUSPICIOUS),
    (re.compile(r"\bdo\s+not\s+tell\s+the\s+user\b|\bhide\s+this\s+from\s+the\s+user\b", re.I), "concealment instruction", InjectionRisk.SUSPICIOUS),
)


class SecurityHardeningRuntime:
    """Transport-independent v9 hardening helpers.

    This layer does not replace SecretVault, ApprovalSecurity, MCP/connectors, or
    existing persistence sanitization. It provides additional deterministic checks
    that those subsystems can call at trust boundaries.
    """

    @staticmethod
    def assess_untrusted_text(value: str) -> InjectionAssessment:
        text = str(value or "")[:200_000]
        reasons: list[str] = []
        risk = InjectionRisk.NONE
        for pattern, reason, rule_risk in _INJECTION_RULES:
            if pattern.search(text):
                reasons.append(reason)
                if rule_risk == InjectionRisk.HIGH:
                    risk = InjectionRisk.HIGH
                elif risk == InjectionRisk.NONE:
                    risk = InjectionRisk.SUSPICIOUS
        return InjectionAssessment(risk=risk, reasons=tuple(dict.fromkeys(reasons)), requires_isolation=risk != InjectionRisk.NONE)

    @staticmethod
    def validate_secret_reference(name: str) -> str:
        value = str(name or "").strip()
        if not value or len(value) > 160:
            raise SecurityHardeningError("secret reference must be between 1 and 160 characters")
        if any(ch in value for ch in ("\n", "\r", "\x00")):
            raise SecurityHardeningError("secret reference contains forbidden control characters")
        if value.lower().startswith(("bearer ", "basic ", "sk-", "ghp_", "github_pat_")):
            raise SecurityHardeningError("plaintext secret material cannot be used as a secret reference")
        return value

    @classmethod
    def assert_no_plaintext_secrets(cls, value: Any, *, path: str = "root") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}"
                if _SECRET_KEY_PATTERN.search(key_text) and item not in (None, "", "[redacted]"):
                    text = str(item)
                    if not text.startswith(("vault:", "secret-ref:", "[redacted]")):
                        raise SecurityHardeningError(f"plaintext secret-like value rejected at {child_path}")
                cls.assert_no_plaintext_secrets(item, path=child_path)
            return
        if isinstance(value, (list, tuple, set)):
            for index, item in enumerate(value):
                cls.assert_no_plaintext_secrets(item, path=f"{path}[{index}]")

    @staticmethod
    def authorize_network_url(
        url: str,
        *,
        allow_external: bool = False,
        allow_private: bool = False,
        allowed_hosts: Iterable[str] = (),
    ) -> NetworkAuthorization:
        raw = str(url or "").strip()
        if len(raw) > 4096 or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
            return NetworkAuthorization(False, "network URL contains invalid control data", "", "")
        try:
            parsed = urlparse(raw)
        except Exception as exc:  # noqa: BLE001
            raise SecurityHardeningError("invalid network URL") from exc
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower().strip(".")
        if scheme not in {"https", "http"} or not host:
            return NetworkAuthorization(False, "only explicit HTTP(S) URLs are supported", host, scheme)
        if parsed.username is not None or parsed.password is not None:
            return NetworkAuthorization(False, "URL userinfo credentials are denied", host, scheme)
        try:
            parsed.port
        except ValueError:
            return NetworkAuthorization(False, "network URL contains an invalid port", host, scheme)

        allowlist = {str(item).lower().strip(".") for item in allowed_hosts if str(item).strip()}
        if any(not item or len(item) > 253 or "/" in item or "@" in item for item in allowlist):
            return NetworkAuthorization(False, "network host allowlist is malformed", host, scheme)

        if host in {"localhost", "host.docker.internal"}:
            return NetworkAuthorization(allow_private, "local/private host requires explicit private-network permission", host, scheme)
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return NetworkAuthorization(allow_private, "private or special-use address requires explicit private-network permission", host, scheme)
        if host in allowlist:
            if scheme != "https":
                return NetworkAuthorization(False, "allowlisted external hosts still require HTTPS", host, scheme)
            return NetworkAuthorization(True, "host explicitly allowed", host, scheme)
        if scheme != "https":
            return NetworkAuthorization(False, "external cleartext HTTP is denied", host, scheme)
        return NetworkAuthorization(bool(allow_external), "external network access requires explicit permission", host, scheme)

    @staticmethod
    def build_audit_envelope(
        *,
        sequence: int,
        event_type: str,
        actor: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
        previous_hash: str = "",
        integrity_key: bytes | None = None,
    ) -> AuditEnvelope:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise SecurityHardeningError("audit sequence must be a non-negative integer")
        if integrity_key is not None and (not isinstance(integrity_key, bytes) or len(integrity_key) < 16):
            raise SecurityHardeningError("audit integrity key must contain at least 16 bytes")
        previous = str(previous_hash or "")
        if previous and not re.fullmatch(r"[0-9a-f]{64}", previous):
            raise SecurityHardeningError("audit previous hash must be an empty value or lowercase SHA-256 digest")
        safe_metadata = sanitize_for_persistence(metadata or {})
        if not isinstance(safe_metadata, dict):
            safe_metadata = {"value": safe_metadata}
        payload = {
            "sequence": sequence,
            "event_type": str(event_type or "")[:200],
            "actor": str(actor or "system")[:200],
            "summary": str(sanitize_for_persistence(str(summary or "")))[:4000],
            "metadata": safe_metadata,
            "previous_hash": previous,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
        digest = hmac.new(integrity_key, encoded, hashlib.sha256).hexdigest() if integrity_key else hashlib.sha256(encoded).hexdigest()
        return AuditEnvelope(event_hash=digest, **payload)

    @staticmethod
    def verify_audit_chain(envelopes: Iterable[AuditEnvelope], *, integrity_key: bytes | None = None) -> bool:
        if integrity_key is not None and (not isinstance(integrity_key, bytes) or len(integrity_key) < 16):
            return False
        previous = ""
        expected_sequence: int | None = None
        try:
            for envelope in envelopes:
                if not isinstance(envelope, AuditEnvelope):
                    return False
                if expected_sequence is None:
                    expected_sequence = envelope.sequence
                if envelope.sequence != expected_sequence or envelope.previous_hash != previous:
                    return False
                if not re.fullmatch(r"[0-9a-f]{64}", str(envelope.event_hash or "")):
                    return False
                rebuilt = SecurityHardeningRuntime.build_audit_envelope(
                    sequence=envelope.sequence,
                    event_type=envelope.event_type,
                    actor=envelope.actor,
                    summary=envelope.summary,
                    metadata=envelope.metadata,
                    previous_hash=envelope.previous_hash,
                    integrity_key=integrity_key,
                )
                if not hmac.compare_digest(rebuilt.event_hash, envelope.event_hash):
                    return False
                previous = envelope.event_hash
                expected_sequence += 1
        except (SecurityHardeningError, TypeError, ValueError):
            return False
        return True


__all__ = [
    "AuditEnvelope",
    "InjectionAssessment",
    "InjectionRisk",
    "NetworkAuthorization",
    "SecurityHardeningError",
    "SecurityHardeningRuntime",
]
