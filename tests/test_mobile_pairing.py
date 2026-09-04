from __future__ import annotations

import hashlib

import pytest

from mobile.pairing import PairingError, PairingManager, PairingPolicy


def test_pairing_challenge_is_short_lived_and_one_time():
    now = [1000.0]
    manager = PairingManager(PairingPolicy(challenge_ttl_seconds=60), clock=lambda: now[0])
    challenge = manager.create_challenge()

    credential = manager.complete_pairing(
        challenge_id=challenge.challenge_id,
        secret=challenge.secret,
        device_id="android-001",
        device_name="Diesel Phone",
    )
    assert credential.device_id == "android-001"
    assert credential.device_name == "Diesel Phone"
    assert credential.token
    assert credential.token_hash == hashlib.sha256(credential.token.encode("utf-8")).hexdigest()

    with pytest.raises(PairingError, match="invalid or already consumed"):
        manager.complete_pairing(
            challenge_id=challenge.challenge_id,
            secret=challenge.secret,
            device_id="android-001",
            device_name="Diesel Phone",
        )


def test_pairing_rejects_wrong_proof_and_consumes_challenge():
    manager = PairingManager(clock=lambda: 1000.0)
    challenge = manager.create_challenge()
    with pytest.raises(PairingError, match="proof rejected"):
        manager.complete_pairing(
            challenge_id=challenge.challenge_id,
            secret="wrong-proof",
            device_id="android-001",
            device_name="Diesel Phone",
        )
    with pytest.raises(PairingError, match="invalid or already consumed"):
        manager.complete_pairing(
            challenge_id=challenge.challenge_id,
            secret=challenge.secret,
            device_id="android-001",
            device_name="Diesel Phone",
        )


def test_expired_pairing_fails_closed():
    now = [1000.0]
    manager = PairingManager(PairingPolicy(challenge_ttl_seconds=30), clock=lambda: now[0])
    challenge = manager.create_challenge()
    now[0] = challenge.expires_at + 1
    with pytest.raises(PairingError, match="expired"):
        manager.complete_pairing(
            challenge_id=challenge.challenge_id,
            secret=challenge.secret,
            device_id="android-001",
            device_name="Diesel Phone",
        )


def test_pairing_manager_stores_only_challenge_digest():
    manager = PairingManager(clock=lambda: 1000.0)
    challenge = manager.create_challenge()
    stored_hash, _ = manager._pending[challenge.challenge_id]
    assert stored_hash != challenge.secret
    assert challenge.secret not in repr(manager._pending)


def test_device_name_is_bounded_and_normalized():
    manager = PairingManager(clock=lambda: 1000.0)
    challenge = manager.create_challenge()
    credential = manager.complete_pairing(
        challenge_id=challenge.challenge_id,
        secret=challenge.secret,
        device_id="android-001",
        device_name="  Diesel    Pixel  ",
    )
    assert credential.device_name == "Diesel Pixel"


def test_pairing_policy_enforces_entropy_and_ttl_bounds():
    with pytest.raises(PairingError):
        PairingPolicy(challenge_ttl_seconds=10).validate()
    with pytest.raises(PairingError):
        PairingPolicy(device_token_bytes=16).validate()
