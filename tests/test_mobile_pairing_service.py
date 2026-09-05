from __future__ import annotations

import pytest

from mobile.auth_boundary import DEVICE_REGISTRY_SETTING, MobileDeviceAuthBoundary
from mobile.device_registry import DeviceRegistryError
from mobile.pairing import PairingError, PairingManager, PairingPolicy
from mobile.pairing_service import MobilePairingService


class FakeStore:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {}
        self.events: list[tuple[str, str, dict[str, object] | None, str]] = []

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key: str, value) -> None:
        self.settings[key] = value

    def audit(self, event_type: str, summary: str, metadata=None, actor: str = "system"):
        self.events.append((event_type, summary, metadata, actor))


def make_service(store: FakeStore, now: list[float]) -> MobilePairingService:
    manager = PairingManager(PairingPolicy(challenge_ttl_seconds=60), clock=lambda: now[0])
    return MobilePairingService(MobileDeviceAuthBoundary(store), pairing_manager=manager)


def test_pairing_registers_hash_only_persistent_device_and_returns_token_once() -> None:
    store = FakeStore()
    now = [1_700_000_000.0]
    service = make_service(store, now)
    challenge = service.create_challenge()

    result = service.complete_pairing(
        challenge_id=challenge["challenge_id"],
        secret=challenge["secret"],
        device_id="android-001",
        device_name="Diesel Phone",
    )

    assert result["device_id"] == "android-001"
    assert len(result["token"]) >= 32
    persisted = store.settings[DEVICE_REGISTRY_SETTING]
    assert result["token"] not in repr(persisted)
    assert "token_hash" in repr(persisted)

    identity = MobileDeviceAuthBoundary(store).authenticate(
        device_id=result["device_id"], credential=result["token"]
    )
    assert identity.device_name == "Diesel Phone"

    with pytest.raises(PairingError, match="already consumed"):
        service.complete_pairing(
            challenge_id=challenge["challenge_id"],
            secret=challenge["secret"],
            device_id="android-001",
            device_name="Diesel Phone",
        )


def test_expired_pairing_never_registers_device() -> None:
    store = FakeStore()
    now = [1000.0]
    service = make_service(store, now)
    challenge = service.create_challenge()
    now[0] = float(challenge["expires_at"] + 1)

    with pytest.raises(PairingError, match="expired"):
        service.complete_pairing(
            challenge_id=challenge["challenge_id"],
            secret=challenge["secret"],
            device_id="android-expired",
            device_name="Expired Phone",
        )

    assert DEVICE_REGISTRY_SETTING not in store.settings


def test_wrong_pairing_proof_never_registers_device() -> None:
    store = FakeStore()
    now = [1000.0]
    service = make_service(store, now)
    challenge = service.create_challenge()

    with pytest.raises(PairingError, match="proof rejected"):
        service.complete_pairing(
            challenge_id=challenge["challenge_id"],
            secret="wrong-proof",
            device_id="android-bad",
            device_name="Bad Phone",
        )

    assert DEVICE_REGISTRY_SETTING not in store.settings


def test_revoke_invalidates_paired_credential_immediately() -> None:
    store = FakeStore()
    now = [1000.0]
    service = make_service(store, now)
    challenge = service.create_challenge()
    result = service.complete_pairing(
        challenge_id=challenge["challenge_id"],
        secret=challenge["secret"],
        device_id="android-revoke",
        device_name="Revoke Phone",
    )

    assert service.revoke_device("android-revoke") is True
    with pytest.raises(DeviceRegistryError, match="rejected"):
        MobileDeviceAuthBoundary(store).authenticate(
            device_id="android-revoke", credential=result["token"]
        )


def test_device_listing_is_secret_free() -> None:
    store = FakeStore()
    now = [1000.0]
    service = make_service(store, now)
    challenge = service.create_challenge()
    result = service.complete_pairing(
        challenge_id=challenge["challenge_id"],
        secret=challenge["secret"],
        device_id="android-list",
        device_name="List Phone",
    )

    devices = service.list_devices()
    assert devices == [
        {
            "device_id": "android-list",
            "device_name": "List Phone",
            "issued_at": 1000,
            "last_seen_at": None,
            "revoked_at": None,
            "active": True,
        }
    ]
    assert result["token"] not in repr(devices)
    assert "token_hash" not in repr(devices)


def test_pairing_transport_contract_has_one_proof_authenticated_public_surface() -> None:
    from pathlib import Path

    source = Path("desktop/service.py").read_text(encoding="utf-8")
    assert '@app.post("/api/v1/mobile/pairing/challenge")' in source
    assert '@app.post("/mobile/v1/pairing/complete")' in source
    assert '@app.get("/api/v1/mobile/devices")' in source
    assert '@app.post("/api/v1/mobile/devices/{device_id}/revoke")' in source
    assert "_mobile_pairing.complete_pairing" in source
    assert "Pairing proof rejected or expired." in source
    assert '/api/v1/mobile/pairing/complete' not in source
