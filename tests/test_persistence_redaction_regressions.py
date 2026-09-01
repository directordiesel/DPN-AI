from __future__ import annotations

from app.persistence_security import sanitize_for_persistence


def test_quoted_json_secret_assignments_are_redacted() -> None:
    raw = 'RuntimeError: upstream payload {"token":"json-secret","password": "quoted-secret","safe":"visible"}'
    sanitized = sanitize_for_persistence(raw)

    assert "json-secret" not in sanitized
    assert "quoted-secret" not in sanitized
    assert '"safe":"visible"' in sanitized
    assert sanitized.count("[redacted]") >= 2


def test_single_quoted_secret_assignments_are_redacted() -> None:
    raw = "diagnostic {'api_key':'single-quoted-secret', 'credential': 'another-secret'}"
    sanitized = sanitize_for_persistence(raw)

    assert "single-quoted-secret" not in sanitized
    assert "another-secret" not in sanitized
    assert sanitized.count("[redacted]") >= 2


def test_bearer_value_inside_quoted_authorization_is_redacted() -> None:
    raw = '{"Authorization":"Bearer bearer-secret-value"}'
    sanitized = sanitize_for_persistence(raw)

    assert "bearer-secret-value" not in sanitized
    assert "[redacted authorization]" in sanitized
