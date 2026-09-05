"""Server-side authentication boundary for DPN AI Mobile requests.

This module binds the Mobile v1 device credential registry to the unified DPN AI
Database settings store without creating a second database or persisting raw
credentials. It is intentionally transport-agnostic so the FastAPI middleware can
call one small fail-closed verifier before accepting a mobile request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from mobile.device_registry import DeviceCredentialRegistry, DeviceRegistryError


DEVICE_REGISTRY_SETTING = "mobile_device_registry_v1"


class SettingsStore(Protocol):
    def get_setting(self, key: str, default: Any = None) -> Any: ...

    def set_setting(self, key: str, value: Any) -> None: ...

    def audit(
        self,
        event_type: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> Any: ...


@dataclass(frozen=True)
class MobileDeviceIdentity:
    device_id: str
    device_name: str


class MobileDeviceAuthBoundary:
    """Validate and administer mobile device credentials in the unified database."""

    def __init__(self, store: SettingsStore) -> None:
        self._store = store
        self._registry = DeviceCredentialRegistry(
            load_state=lambda: self._store.get_setting(DEVICE_REGISTRY_SETTING, {}),
            save_state=lambda state: self._store.set_setting(DEVICE_REGISTRY_SETTING, state),
        )

    def authenticate(self, *, device_id: str, credential: str) -> MobileDeviceIdentity:
        """Return a secret-free identity or fail closed with DeviceRegistryError."""
        try:
            record = self._registry.validate(device_id=device_id, token=credential, touch=True)
        except DeviceRegistryError:
            self._audit_rejection(device_id)
            raise
        return MobileDeviceIdentity(device_id=record.device_id, device_name=record.device_name)

    def register(
        self,
        *,
        device_id: str,
        device_name: str,
        credential: str,
        issued_at: int | None = None,
    ) -> MobileDeviceIdentity:
        """Persist only the credential digest and bounded device metadata."""
        record = self._registry.register(
            device_id=device_id,
            device_name=device_name,
            token=credential,
            issued_at=issued_at,
        )
        self._audit(
            "mobile.device_registered",
            "Registered mobile device credential",
            {"device_id": record.device_id, "device_name": record.device_name},
        )
        return MobileDeviceIdentity(device_id=record.device_id, device_name=record.device_name)

    def revoke(self, device_id: str) -> bool:
        """Persistently revoke a mobile device credential immediately."""
        revoked = self._registry.revoke(device_id)
        if revoked:
            self._audit(
                "mobile.device_revoked",
                "Revoked mobile device credential",
                {"device_id": device_id.strip()[:128]},
            )
        return revoked

    def list_devices(self) -> list[dict[str, Any]]:
        """Return secret-free device metadata suitable for desktop administration."""
        return self._registry.list_devices()

    def _audit_rejection(self, device_id: str) -> None:
        self._audit(
            "mobile.device_auth_rejected",
            "Rejected mobile device credential",
            {"device_id": device_id.strip()[:128]},
        )

    def _audit(self, event_type: str, summary: str, metadata: dict[str, Any]) -> None:
        try:
            self._store.audit(event_type, summary, metadata, actor="mobile")
        except Exception:
            # Authentication/authorization must never become permissive because audit storage is unavailable.
            pass


__all__ = [
    "DEVICE_REGISTRY_SETTING",
    "MobileDeviceAuthBoundary",
    "MobileDeviceIdentity",
]
