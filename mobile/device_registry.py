"""Persistent device credential authority for DPN AI Mobile.

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
    MIN_TOKEN_LENGTH = 32
    MAX_TOKEN_LENGTH = 512

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
    def _normalize_device_id(cls, device_id: str) -> str:
        if not isinstance(device_id, str):
            raise DeviceRegistryError("invalid device identifier")
        clean_id = device_id.strip()
        if (
            not clean_id
            or len(clean_id) > cls.MAX_DEVICE_ID_LENGTH
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in clean_id)
        ):
            raise DeviceRegistryError("invalid device identifier")
        return clean_id

    @classmethod
    def _normalize_identity(cls, device_id: str, device_name: str) -> tuple[str, str]:
        clean_id = cls._normalize_device_id(device_id)
        if not isinstance(device_name, str):
            raise DeviceRegistryError("invalid device name")
        clean_name = " ".join(device_name.split())
        if (
            not clean_name
            or len(clean_name) > cls.MAX_DEVICE_NAME_LENGTH
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in clean_name)
        ):
            raise DeviceRegistryError("invalid device name")
        return clean_id, clean_name

    @staticmethod
    def _strict_timestamp(value: Any, field: str, *, allow_none: bool = False) -> int | None:
        if value is None and allow_none:
            return None
        if type(value) is not int or value <= 0:
            raise DeviceRegistryError(f"device {field} timestamp is invalid")
        return value

    @classmethod
    def _validate_token(cls, token: str) -> str:
        if not isinstance(token, str):
            raise DeviceRegistryError("device credential is invalid")
        if len(token) < cls.MIN_TOKEN_LENGTH:
            raise DeviceRegistryError("device credential is too short")
        if len(token) > cls.MAX_TOKEN_LENGTH or any(ch in token for ch in "\r\n\x00"):
            raise DeviceRegistryError("device credential is invalid")
        return token

    def _now(self) -> int:
        try:
            value = int(self._clock())
        except (TypeError, ValueError, OverflowError) as exc:
            raise DeviceRegistryError("device clock is invalid") from exc
        if value <= 0:
            raise DeviceRegistryError("device clock is invalid")
        return value

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
            raw_name = raw.get("device_name")
            if not isinstance(raw_name, str):
                raise DeviceRegistryError("invalid device name")
            device_id, device_name = self._normalize_identity(key, raw_name)
            token_hash = raw.get("token_hash")
            if not isinstance(token_hash, str) or len(token_hash) != 64 or any(
                ch not in "0123456789abcdef" for ch in token_hash
            ):
                raise DeviceRegistryError("device token digest is invalid")
            issued_at = self._strict_timestamp(raw.get("issued_at"), "issue")
            last_seen = self._strict_timestamp(raw.get("last_seen_at"), "last-seen", allow_none=True)
            revoked = self._strict_timestamp(raw.get("revoked_at"), "revocation", allow_none=True)
            assert issued_at is not None
            if last_seen is not None and last_seen < issued_at:
                raise DeviceRegistryError("device last-seen timestamp predates issuance")
            if revoked is not None and revoked < issued_at:
                raise DeviceRegistryError("device revocation timestamp predates issuance")
            records[device_id] = DeviceRecord(
                device_id=device_id,
                device_name=device_name,
                token_hash=token_hash,
                issued_at=issued_at,
                last_seen_at=last_seen,
                revoked_at=revoked,
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
        clean_token = self._validate_token(token)
        records = self._read()
        existing = records.get(clean_id)
        if existing is not None and existing.active:
            raise DeviceRegistryError("active device must be revoked before re-pairing")
        if existing is None and len(records) >= self.MAX_DEVICES:
            raise DeviceRegistryError("device registry is full")
        now = self._now() if issued_at is None else self._strict_timestamp(issued_at, "issue")
        assert now is not None
        record = DeviceRecord(clean_id, clean_name, self._digest(clean_token), now)
        records[clean_id] = record
        self._write(records)
        return record

    def validate(self, *, device_id: str, token: str, touch: bool = True) -> DeviceRecord:
        clean_id = self._normalize_device_id(device_id)
        if not isinstance(token, str) or not token:
            raise DeviceRegistryError("device identity and credential are required")
        if len(token) > self.MAX_TOKEN_LENGTH or any(ch in token for ch in "\r\n\x00"):
            raise DeviceRegistryError("device credential rejected")
        records = self._read()
        record = records.get(clean_id)
        if record is None or not record.active:
            raise DeviceRegistryError("device credential rejected")
        if not hmac.compare_digest(record.token_hash, self._digest(token)):
            raise DeviceRegistryError("device credential rejected")
        if not touch:
            return record
        now = self._now()
        if now < record.issued_at:
            raise DeviceRegistryError("device clock predates credential issuance")
        updated = DeviceRecord(
            device_id=record.device_id,
            device_name=record.device_name,
            token_hash=record.token_hash,
            issued_at=record.issued_at,
            last_seen_at=max(now, record.last_seen_at or record.issued_at),
            revoked_at=None,
        )
        records[clean_id] = updated
        self._write(records)
        return updated

    def revoke(self, device_id: str) -> bool:
        clean_id = self._normalize_device_id(device_id)
        records = self._read()
        record = records.get(clean_id)
        if record is None or not record.active:
            return False
        now = self._now()
        if now < record.issued_at:
            raise DeviceRegistryError("device clock predates credential issuance")
        records[clean_id] = DeviceRecord(
            device_id=record.device_id,
            device_name=record.device_name,
            token_hash=record.token_hash,
            issued_at=record.issued_at,
            last_seen_at=record.last_seen_at,
            revoked_at=max(now, record.last_seen_at or record.issued_at),
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
