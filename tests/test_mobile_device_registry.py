from __future__ import annotations

import pytest

from mobile.device_registry import DeviceCredentialRegistry, DeviceRegistryError


def make_registry(now: int = 1000):
    state: dict = {}

    def load_state():
        return state.copy()

    def save_state(value):
        state.clear()
        state.update(value)

    registry = DeviceCredentialRegistry(load_state=load_state, save_state=save_state, clock=lambda: now)
    return registry, state


def test_registry_persists_only_token_digest():
    registry, state = make_registry()
    token = "T" * 48
    record = registry.register(device_id="android-001", device_name="Diesel Phone", token=token)

    assert record.token_hash != token
    assert token not in repr(state)
    assert state["devices"]["android-001"]["token_hash"] == record.token_hash


def test_valid_device_credential_is_constant_contract_and_updates_last_seen():
    registry, state = make_registry(now=2000)
    token = "A" * 48
    registry.register(device_id="android-001", device_name="Diesel Phone", token=token, issued_at=1000)

    result = registry.validate(device_id="android-001", token=token)

    assert result.active is True
    assert result.last_seen_at == 2000
    assert state["devices"]["android-001"]["last_seen_at"] == 2000


def test_wrong_device_token_fails_closed_without_revealing_reason():
    registry, _ = make_registry()
    registry.register(device_id="android-001", device_name="Diesel Phone", token="A" * 48)

    with pytest.raises(DeviceRegistryError, match="device credential rejected"):
        registry.validate(device_id="android-001", token="B" * 48)
    with pytest.raises(DeviceRegistryError, match="device credential rejected"):
        registry.validate(device_id="missing-device", token="B" * 48)


def test_revocation_is_persistent_and_immediate():
    registry, state = make_registry(now=3000)
    token = "A" * 48
    registry.register(device_id="android-001", device_name="Diesel Phone", token=token, issued_at=1000)

    assert registry.revoke("android-001") is True
    assert state["devices"]["android-001"]["revoked_at"] == 3000
    with pytest.raises(DeviceRegistryError, match="device credential rejected"):
        registry.validate(device_id="android-001", token=token)


def test_repairing_same_device_rotates_credential_and_reactivates():
    registry, _ = make_registry(now=4000)
    old_token = "A" * 48
    new_token = "B" * 48
    registry.register(device_id="android-001", device_name="Diesel Phone", token=old_token, issued_at=1000)
    registry.revoke("android-001")
    registry.register(device_id="android-001", device_name="Diesel Phone", token=new_token, issued_at=4000)

    with pytest.raises(DeviceRegistryError):
        registry.validate(device_id="android-001", token=old_token, touch=False)
    assert registry.validate(device_id="android-001", token=new_token, touch=False).active is True


def test_device_list_never_exposes_token_hash_or_raw_token():
    registry, _ = make_registry()
    registry.register(device_id="android-001", device_name="Diesel Phone", token="A" * 48)

    devices = registry.list_devices()

    assert devices[0]["device_id"] == "android-001"
    assert "token" not in devices[0]
    assert "token_hash" not in devices[0]


def test_corrupt_registry_state_fails_closed():
    state = {"version": 1, "devices": {"android-001": {"device_name": "Diesel Phone", "token_hash": "bad", "issued_at": 1000}}}
    registry = DeviceCredentialRegistry(load_state=lambda: state, save_state=lambda _: None)

    with pytest.raises(DeviceRegistryError, match="digest"):
        registry.list_devices()


def test_registry_rejects_short_tokens_and_unbounded_identity():
    registry, _ = make_registry()
    with pytest.raises(DeviceRegistryError, match="too short"):
        registry.register(device_id="android-001", device_name="Diesel Phone", token="short")
    with pytest.raises(DeviceRegistryError, match="identifier"):
        registry.register(device_id="x" * 129, device_name="Diesel Phone", token="A" * 48)
