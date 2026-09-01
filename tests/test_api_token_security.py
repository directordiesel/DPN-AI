from __future__ import annotations

from app.config import ConstantTimeSecret


def test_constant_time_secret_matches_from_either_operand() -> None:
    secret = ConstantTimeSecret("correct-token")
    assert secret == "correct-token"
    assert "correct-token" == secret
    assert not (secret != "correct-token")
    assert not ("correct-token" != secret)


def test_constant_time_secret_rejects_wrong_values_and_non_strings() -> None:
    secret = ConstantTimeSecret("correct-token")
    assert secret != "wrong-token"
    assert "wrong-token" != secret
    assert secret != 12345


def test_constant_time_secret_preserves_string_compatibility() -> None:
    secret = ConstantTimeSecret("abc123")
    assert isinstance(secret, str)
    assert secret.encode("utf-8") == b"abc123"
    assert bool(secret)
