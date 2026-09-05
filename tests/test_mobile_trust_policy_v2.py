import pytest

from mobile.trust_policy_v2 import (
    ConnectionMode,
    DeviceTrustContext,
    MobileTrustPolicyV2,
    TrustPolicyError,
)


def test_local_read_allows_current_paired_device():
    policy = MobileTrustPolicyV2()
    result = policy.evaluate(DeviceTrustContext(device_id="android-1", paired=True), "read")
    assert result["ok"] is True
    assert result["approval_required"] is False
    assert result["max_session_age_seconds"] == 24 * 60 * 60


def test_revoked_or_unpaired_device_fails_closed():
    policy = MobileTrustPolicyV2()
    denied = policy.evaluate(DeviceTrustContext(device_id="android-1", paired=False), "chat")
    assert "device_not_paired" in denied["failures"]
    revoked = policy.evaluate(DeviceTrustContext(device_id="android-1", paired=True, revoked=True), "read")
    assert "device_revoked" in revoked["failures"]


def test_remote_write_requires_gateway_and_user_presence():
    policy = MobileTrustPolicyV2()
    denied = policy.evaluate(
        DeviceTrustContext(device_id="phone", paired=True, connection_mode=ConnectionMode.REMOTE),
        "update",
    )
    assert set(denied["failures"]) == {"remote_gateway_not_authenticated", "user_presence_required"}

    allowed = policy.evaluate(
        DeviceTrustContext(
            device_id="phone",
            paired=True,
            connection_mode=ConnectionMode.REMOTE,
            remote_gateway_authenticated=True,
            user_presence_confirmed=True,
        ),
        "update",
    )
    assert allowed["ok"] is True


def test_destructive_mobile_action_requires_explicit_approval():
    policy = MobileTrustPolicyV2()
    denied = policy.evaluate(
        DeviceTrustContext(
            device_id="phone",
            paired=True,
            connection_mode=ConnectionMode.REMOTE,
            remote_gateway_authenticated=True,
            user_presence_confirmed=True,
        ),
        "execute",
    )
    assert "approval_required" in denied["failures"]

    allowed = policy.evaluate(
        DeviceTrustContext(
            device_id="phone",
            paired=True,
            connection_mode=ConnectionMode.REMOTE,
            remote_gateway_authenticated=True,
            user_presence_confirmed=True,
            approval_present=True,
        ),
        "execute",
    )
    assert allowed["ok"] is True
    assert allowed["risk"] == "destructive"


def test_remote_sessions_expire_more_quickly_than_local_sessions():
    policy = MobileTrustPolicyV2()
    result = policy.evaluate(
        DeviceTrustContext(
            device_id="phone",
            paired=True,
            connection_mode=ConnectionMode.REMOTE,
            remote_gateway_authenticated=True,
            session_age_seconds=8 * 60 * 60 + 1,
        ),
        "read",
    )
    assert "session_expired" in result["failures"]
    assert result["max_session_age_seconds"] == 8 * 60 * 60


def test_invalid_device_and_unknown_operation_are_rejected():
    policy = MobileTrustPolicyV2()
    with pytest.raises(TrustPolicyError, match="device identifier"):
        policy.evaluate(DeviceTrustContext(device_id="bad\ndevice", paired=True), "read")
    with pytest.raises(TrustPolicyError, match="unsupported"):
        policy.evaluate(DeviceTrustContext(device_id="phone", paired=True), "shell")


def test_transport_like_truthy_values_cannot_forge_authorization_flags():
    policy = MobileTrustPolicyV2()
    with pytest.raises(TrustPolicyError, match="paired"):
        policy.evaluate(DeviceTrustContext(device_id="phone", paired="true"), "read")  # type: ignore[arg-type]
    with pytest.raises(TrustPolicyError, match="approval present"):
        policy.evaluate(
            DeviceTrustContext(device_id="phone", paired=True, approval_present=1),  # type: ignore[arg-type]
            "execute",
        )


def test_invalid_connection_modes_and_session_ages_fail_closed():
    policy = MobileTrustPolicyV2()
    with pytest.raises(TrustPolicyError, match="connection mode"):
        policy.evaluate(
            DeviceTrustContext(device_id="phone", paired=True, connection_mode="vpn"),  # type: ignore[arg-type]
            "read",
        )
    with pytest.raises(TrustPolicyError, match="session age"):
        policy.evaluate(DeviceTrustContext(device_id="phone", paired=True, session_age_seconds=True), "read")
    with pytest.raises(TrustPolicyError, match="session age"):
        policy.evaluate(DeviceTrustContext(device_id="phone", paired=True, session_age_seconds=-1), "read")


def test_valid_string_connection_mode_is_normalized_explicitly():
    policy = MobileTrustPolicyV2()
    result = policy.evaluate(
        DeviceTrustContext(
            device_id="phone",
            paired=True,
            connection_mode=" REMOTE ",  # type: ignore[arg-type]
            remote_gateway_authenticated=True,
        ),
        "read",
    )
    assert result["ok"] is True
    assert result["connection_mode"] == "remote"
