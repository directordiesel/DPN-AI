from __future__ import annotations

import secrets


def access_token_matches(supplied: str, expected: str) -> bool:
    """Compare API access tokens without data-dependent early-exit behavior."""
    if not expected:
        return False
    return secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def public_server_error_detail(error_id: str) -> str:
    """Return a client-safe generic error message that does not expose internals."""
    return f"DPN AI encountered an internal server error. Error ID {error_id}."
