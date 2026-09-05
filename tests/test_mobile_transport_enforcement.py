from __future__ import annotations

from pathlib import Path

import pytest

from mobile.auth_boundary import DEVICE_REGISTRY_SETTING, MobileDeviceAuthBoundary
from mobile.device_registry import DeviceRegistryError


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


def test_register_authenticate_and_revoke_are_persistent_and_hash_only() -> None:
    store = FakeStore()
    authority = MobileDeviceAuthBoundary(store)
    token = "A" * 48

    identity = authority.register(
        device_id="phone-1",
        device_name="Diesel Phone",
        credential=token,
        issued_at=1_700_000_000,
    )
    assert identity.device_id == "phone-1"

    state = store.settings[DEVICE_REGISTRY_SETTING]
    assert token not in repr(state)
    assert "token_hash" in repr(state)

    verified = MobileDeviceAuthBoundary(store).authenticate(device_id="phone-1", credential=token)
    assert verified == identity

    assert authority.revoke("phone-1") is True
    with pytest.raises(DeviceRegistryError, match="rejected"):
        MobileDeviceAuthBoundary(store).authenticate(device_id="phone-1", credential=token)


def test_wrong_mobile_credential_fails_closed_and_is_audited() -> None:
    store = FakeStore()
    authority = MobileDeviceAuthBoundary(store)
    authority.register(device_id="phone-2", device_name="Phone", credential="B" * 48, issued_at=1_700_000_000)

    with pytest.raises(DeviceRegistryError, match="rejected"):
        authority.authenticate(device_id="phone-2", credential="C" * 48)

    assert any(event[0] == "mobile.device_auth_rejected" for event in store.events)


def test_desktop_service_enforces_device_registry_before_internal_token_translation() -> None:
    source = Path("desktop/service.py").read_text(encoding="utf-8")

    assert 'request.headers.get("X-DPN-Device-ID"' in source
    assert 'request.headers.get("X-DPN-Token"' in source
    assert "_mobile_auth.authenticate" in source
    assert "except DeviceRegistryError" in source
    assert 'status_code=401' in source
    assert "settings.access_token.encode" in source
    assert 'request.scope["client"] = ("127.0.0.1", 0)' in source

    auth_pos = source.index("_mobile_auth.authenticate")
    translate_pos = source.index("settings.access_token.encode")
    assert auth_pos < translate_pos


def test_desktop_requests_without_device_header_keep_existing_authorization_path() -> None:
    source = Path("desktop/service.py").read_text(encoding="utf-8")
    guard = 'if path.startswith("/api") and device_id:'
    assert guard in source
    assert "return await call_next(request)" in source
