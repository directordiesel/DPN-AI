"""Security primitives for DPN AI Mobile v1 desktop pairing.

This module deliberately contains no transport server and no Android-specific code.
It defines the device-scoped, one-time pairing contracts used by the unified desktop
service and future Android client without creating a second AI/runtime.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Callable


class PairingError(ValueError):
    """Raised when a pairing request violates the mobile security contract."""


@dataclass(frozen=True)
class PairingPolicy:
    challenge_ttl_seconds: int = 180
    device_token_bytes: int = 32
    max_device_name_length: int = 80

    def validate(self) -> None:
        if not 30 <= self.challenge_ttl_seconds <= 600:
            raise PairingError("pairing challenge TTL must be between 30 and 600 seconds")
        if not 32 <= self.device_token_bytes <= 64:
            raise PairingError("device token entropy must be between 32 and 64 bytes")
        if not 16 <= self.max_device_name_length <= 120:
            raise PairingError("device name limit must be between 16 and 120 characters")


@dataclass(frozen=True)
class PairingChallenge:
    challenge_id: str
    secret: str
    expires_at: int


@dataclass(frozen=True)
class PairedDeviceCredential:
    device_id: str
    device_name: str
    token: str
    token_hash: str
    issued_at: int


class PairingManager:
    def __init__(
        self,
        policy: PairingPolicy | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy or PairingPolicy()
        self.policy.validate()
        self._clock = clock
        self._pending: dict[str, tuple[str, int]] = {}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create_challenge(self) -> PairingChallenge:
        now = int(self._clock())
        challenge_id = secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(24)
        expires_at = now + self.policy.challenge_ttl_seconds
        self._pending[challenge_id] = (self._digest(secret), expires_at)
        return PairingChallenge(challenge_id=challenge_id, secret=secret, expires_at=expires_at)

    def complete_pairing(
        self,
        *,
        challenge_id: str,
        secret: str,
        device_id: str,
        device_name: str,
    ) -> PairedDeviceCredential:
        if not challenge_id or not secret:
            raise PairingError("pairing challenge and proof are required")
        pending = self._pending.pop(challenge_id, None)
        if pending is None:
            raise PairingError("pairing challenge is invalid or already consumed")

        expected_hash, expires_at = pending
        now = int(self._clock())
        if now > expires_at:
            raise PairingError("pairing challenge expired")
        if not hmac.compare_digest(expected_hash, self._digest(secret)):
            raise PairingError("pairing proof rejected")

        clean_id = device_id.strip()
        clean_name = " ".join(device_name.split())
        if not clean_id or len(clean_id) > 128:
            raise PairingError("invalid device identifier")
        if not clean_name or len(clean_name) > self.policy.max_device_name_length:
            raise PairingError("invalid device name")

        token = secrets.token_urlsafe(self.policy.device_token_bytes)
        return PairedDeviceCredential(
            device_id=clean_id,
            device_name=clean_name,
            token=token,
            token_hash=self._digest(token),
            issued_at=now,
        )

    def revoke_challenge(self, challenge_id: str) -> bool:
        return self._pending.pop(challenge_id, None) is not None

    def purge_expired(self) -> int:
        now = int(self._clock())
        expired = [key for key, (_, expires_at) in self._pending.items() if now > expires_at]
        for key in expired:
            self._pending.pop(key, None)
        return len(expired)


__all__ = [
    "PairingChallenge",
    "PairedDeviceCredential",
    "PairingError",
    "PairingManager",
    "PairingPolicy",
]
