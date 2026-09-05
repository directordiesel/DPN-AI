from __future__ import annotations

import pytest

from mobile.auth_boundary import DEVICE_REGISTRY_SETTING, MobileDeviceAuthBoundary
from mobile.device_registry import DeviceCredentialRegistry, DeviceRegistryError


class FakeStore:
    def __init__(self) -> None:
        self.settings: dict[str, object] = {}
        self.events: list[dict[str, object]] = []

    def get_setting(self, key: str, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key: str, value) -> None:
        self.settings[key] = value

    def audit(self, event_type: str, summary: str, metadata=None, actor: str = "system") -> None:
        self.events.append(
            {
                "event_type": event_type,
                "summary": summary,
                "metadata": metadata or {},
                "actor": actor,
            }
        )


def seed_device(store: FakeStore, *, device_id: str = "android-1", token: str = "t" * 48) -> None:
    registry = DeviceCredentialRegistry(
        load_state=lambda: store.get_setting(DEVICE_REGISTRY_SETTING, {}),
        save_state=lambda state: store.set_setting(DEVICE_REGISTRY_SETTING, state),
        clock=lambda: 1000,
    )
    registry.register(device_id=device_id, device_name="Diesel Phone", token=token)


def test_authenticate_returns_secret_free_identity_and_touches_registry() -> None:
    store = FakeStore()
    token = "a" * 48
    seed_device(store, token=token)

    identity = MobileDeviceAuthBoundary(store).authenticate(device_id="android-1", credential=token)

    assert identity.device_id == "android-1"
    assert identity.device_name == "Diesel Phone"
    assert token not in repr(identity)
    persisted = store.settings[DEVICE_REGISTRY_SETTING]
    assert isinstance(persisted, dict)
    device = persisted["devices"]["android-1"]
    assert token not in str(device)
    assert isinstance(device["last_seen_at"], int)


def test_invalid_credential_fails_closed_and_audits_without_secret() -> None:
    store = FakeStore()
    seed_device(store, token="b" * 48)
    supplied = "c" * 48

    with pytest.raises(DeviceRegistryError, match="device credential rejected"):
        MobileDeviceAuthBoundary(store).authenticate(device_id="android-1", credential=supplied)

    assert store.events[-1]["event_type"] == "mobile.device_auth_rejected"
    assert store.events[-1]["metadata"] == {"device_id": "android-1"}
    assert supplied not in str(store.events)


def test_missing_device_identity_fails_closed() -> None:
    store = FakeStore()

    with pytest.raises(DeviceRegistryError):
        MobileDeviceAuthBoundary(store).authenticate(device_id="", credential="x" * 48)


def test_revoked_device_is_rejected() -> None:
    store = FakeStore()
    token = "d" * 48
    seed_device(store, token=token)
    registry = DeviceCredentialRegistry(
        load_state=lambda: store.get_setting(DEVICE_REGISTRY_SETTING, {}),
        save_state=lambda state: store.set_setting(DEVICE_REGISTRY_SETTING, state),
    )
    assert registry.revoke("android-1") is True

    with pytest.raises(DeviceRegistryError, match="device credential rejected"):
        MobileDeviceAuthBoundary(store).authenticate(device_id="android-1", credential=token)


def test_corrupt_registry_state_fails_closed() -> None:
    store = FakeStore()
    store.settings[DEVICE_REGISTRY_SETTING] = {"version": 1, "devices": {"android-1": {"device_name": "Phone"}}}

    with pytest.raises(DeviceRegistryError):
        MobileDeviceAuthBoundary(store).authenticate(device_id="android-1", credential="e" * 48)
