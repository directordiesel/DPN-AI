"""End-to-end Mobile v1 pairing service for the unified DPN AI runtime.

The pairing manager owns only short-lived, in-memory one-time challenges. Successful
pairing is immediately committed to the persistent hash-only mobile device registry
through ``MobileDeviceAuthBoundary``. Raw device credentials are returned exactly
once to the Android client and are never written to desktop persistence or audit
metadata.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mobile.auth_boundary import MobileDeviceAuthBoundary
from mobile.pairing import PairingChallenge, PairingError, PairingManager


class MobilePairingService:
    """Coordinate one-time pairing and persistent device authority registration."""

    def __init__(
        self,
        auth_boundary: MobileDeviceAuthBoundary,
        *,
        pairing_manager: PairingManager | None = None,
    ) -> None:
        self._auth = auth_boundary
        self._pairing = pairing_manager or PairingManager()

    def create_challenge(self) -> dict[str, Any]:
        challenge: PairingChallenge = self._pairing.create_challenge()
        return asdict(challenge)

    def complete_pairing(
        self,
        *,
        challenge_id: str,
        secret: str,
        device_id: str,
        device_name: str,
    ) -> dict[str, Any]:
        """Consume a valid challenge, persist the digest, and return the raw token once."""
        credential = self._pairing.complete_pairing(
            challenge_id=challenge_id,
            secret=secret,
            device_id=device_id,
            device_name=device_name,
        )
        self._auth.register(
            device_id=credential.device_id,
            device_name=credential.device_name,
            credential=credential.token,
            issued_at=credential.issued_at,
        )
        return {
            "device_id": credential.device_id,
            "device_name": credential.device_name,
            "token": credential.token,
            "issued_at": credential.issued_at,
        }

    def revoke_device(self, device_id: str) -> bool:
        return self._auth.revoke(device_id)

    def list_devices(self) -> list[dict[str, Any]]:
        return self._auth.list_devices()

    def purge_expired_challenges(self) -> int:
        return self._pairing.purge_expired()


__all__ = ["MobilePairingService", "PairingError"]
