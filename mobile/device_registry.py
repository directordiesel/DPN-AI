"""Persistent device credential authority for DPN AI Mobile v1.

The registry stores only SHA-256 token digests and bounded device metadata. Raw
mobile credentials are returned once at pairing time and must never be persisted
by the desktop service. Storage is injected so the unified DPN AI database can own
persistence without creating a second mobile database/runtime.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class DeviceRegistryError(ValueError):
    """Raised when device credential state violates the mobile security contract."""


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    device_name: str
    token_hash: str
    issued_at: int
    last_seen_at: int | None = None
    revoked_at: int | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class DeviceCredentialRegistry:
    """Hash-only mobile device registry backed by injected persistence callbacks."""

    STORAGE_VERSION = 1
    MAX_DEVICES = 100
    MAX_DEVICE_ID_LENGTH = 128
    MAX_DEVICE_NAME_LENGTH = 80

    def __init__(
        self,
        *,
        load_state: Callable[[], Mapping[str, Any] | None],
        save_state: Callable[[dict[str, Any]], None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._load_state = load_state
        self._save_state = save_state
        self._clock = clock

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @classmethod
    def _normalize_identity(cls, device_id: str, device_name: str) -> tuple[str, str]:
        clean_id = device_id.strip()
        clean_name = " ".join(device_name.split())
        if not clean_id or len(clean_id) > cls.MAX_DEVICE_ID_LENGTH:
            raise DeviceRegistryError("invalid device identifier")
        if not clean_name or len(clean_name) > cls.MAX_DEVICE_NAME_LENGTH:
            raise DeviceRegistryError("invalid device name")
        return clean_id, clean_name

    def _read(self) -> dict[str, DeviceRecord]:
        state = self._load_state() or {}
        if not isinstance(state, Mapping):
            raise DeviceRegistryError("device registry state is invalid")
        version = state.get("version", self.STORAGE_VERSION)
        if version != self.STORAGE_VERSION:
            raise DeviceRegistryError("unsupported device registry version")
        raw_devices = state.get("devices", {})
        if not isinstance(raw_devices, Mapping):
            raise DeviceRegistryError("device registry entries are invalid")
        if len(raw_devices) > self.MAX_DEVICES:
            raise DeviceRegistryError("device registry exceeds safety limit")

        records: dict[str, DeviceRecord] = {}
        for key, raw in raw_devices.items():
            if not isinstance(key, str) or not isinstance(raw, Mapping):
                raise DeviceRegistryError("device registry entry is invalid")
            device_id, device_name = self._normalize_identity(key, str(raw.get("device_name", "")))
            token_hash = str(raw.get("token_hash", ""))
            if len(token_hash) != 64 or any(ch not in "0123456789abcdef" for ch in token_hash):
                raise DeviceRegistryError("device token digest is invalid")
            issued_at = int(raw.get("issued_at", 0))
            if issued_at <= 0:
                raise DeviceRegistryError("device issue timestamp is invalid")
            last_seen = raw.get("last_seen_at")
            revoked = raw.get("revoked_at")
            records[device_id] = DeviceRecord(
                device_id=device_id,
                device_name=device_name,
                token_hash=token_hash,
                issued_at=issued_at,
                last_seen_at=int(last_seen) if last_seen is not None else None,
                revoked_at=int(revoked) if revoked is not None else None,
            )
        return records

    def _write(self, records: Mapping[str, DeviceRecord]) -> None:
        if len(records) > self.MAX_DEVICES:
            raise DeviceRegistryError("device registry exceeds safety limit")
        payload = {
            "version": self.STORAGE_VERSION,
            "devices": {
                device_id: {
                    "device_name": record.device_name,
                    "token_hash": record.token_hash,
                    "issued_at": record.issued_at,
                    "last_seen_at": record.last_seen_at,
                    "revoked_at": record.revoked_at,
                }
                for device_id, record in sorted(records.items())
            },
        }
        self._save_state(payload)

    def register(self, *, device_id: str, device_name: str, token: str, issued_at: int | None = None) -> DeviceRecord:
        clean_id, clean_name = self._normalize_identity(device_id, device_name)
        if not token or len(token) < 32:
            raise DeviceRegistryError("device credential is too short")
        records = self._read()
        if clean_id not in records and len(records) >= self.MAX_DEVICES:
            raise DeviceRegistryError("device registry is full")
        now = int(self._clock()) if issued_at is None else int(issued_at)
        if now <= 0:
            raise DeviceRegistryError("device issue timestamp is invalid")
        record = DeviceRecord(clean_id, clean_name, self._digest(token), now)
        records[clean_id] = record
        self._write(records)
        return record

    def validate(self, *, device_id: str, token: str, touch: bool = True) -> DeviceRecord:
        clean_id = device_id.strip()
        if not clean_id or not token:
            raise DeviceRegistryError("device identity and credential are required")
        records = self._read()
        record = records.get(clean_id)
        if record is None or not record.active:
            raise DeviceRegistryError("device credential rejected")
        if not hmac.compare_digest(record.token_hash, self._digest(token)):
            raise DeviceRegistryError("device credential rejected")
        if not touch:
            return record
        updated = DeviceRecord(
            device_id=record.device_id,
            device_name=record.device_name,
            token_hash=record.token_hash,
            issued_at=record.issued_at,
            last_seen_at=int(self._clock()),
            revoked_at=None,
        )
        records[clean_id] = updated
        self._write(records)
        return updated

    def revoke(self, device_id: str) -> bool:
        clean_id = device_id.strip()
        records = self._read()
        record = records.get(clean_id)
        if record is None or not record.active:
            return False
        records[clean_id] = DeviceRecord(
            device_id=record.device_id,
            device_name=record.device_name,
            token_hash=record.token_hash,
            issued_at=record.issued_at,
            last_seen_at=record.last_seen_at,
            revoked_at=int(self._clock()),
        )
        self._write(records)
        return True

    def list_devices(self) -> list[dict[str, Any]]:
        """Return secret-free device metadata suitable for the Control Center."""
        return [
            {
                "device_id": record.device_id,
                "device_name": record.device_name,
                "issued_at": record.issued_at,
                "last_seen_at": record.last_seen_at,
                "revoked_at": record.revoked_at,
                "active": record.active,
            }
            for record in self._read().values()
        ]


__all__ = ["DeviceCredentialRegistry", "DeviceRecord", "DeviceRegistryError"]
