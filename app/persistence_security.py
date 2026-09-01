from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEY_TOKENS = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "passwd",
    "secret",
    "private_key",
    "credential",
    "cookie",
    "session",
)
MAX_PERSISTED_STRING = 8_000
MAX_COLLECTION_ITEMS = 200
MAX_DEPTH = 8
_AUTH_REDACTION_SENTINEL = "\x00DPN_AUTH_REDACTED\x00"

_AUTH_VALUE = re.compile(r"^(?:bearer|basic)\s+\S+", re.IGNORECASE)
_INLINE_AUTH_VALUE = re.compile(r"\b(?:bearer|basic)\s+[^\s,;]+", re.IGNORECASE)
_QUOTED_AUTH_ASSIGNMENT = re.compile(
    r"(?i)([\"']?\bauthorization\b[\"']?\s*[:=]\s*)([\"'])(?:bearer|basic)\s+.*?\2"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?\b(?:authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|token|password|passwd|secret|credential)"
    r"\b[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;}&]+)([\"']?)"
)
_SECRET_REF = re.compile(r"^\{\{secret:[A-Za-z0-9_.-]{1,100}\}\}$")


def _sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(token in normalized for token in SENSITIVE_KEY_TOKENS)


def _sanitize_text(value: str) -> str:
    if _SECRET_REF.fullmatch(value):
        return "[secret reference]"
    if _AUTH_VALUE.match(value.strip()):
        return "[redacted authorization]"
    redacted = _QUOTED_AUTH_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{_AUTH_REDACTION_SENTINEL}{match.group(2)}",
        value,
    )
    redacted = _INLINE_AUTH_VALUE.sub("[redacted authorization]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}[redacted]{match.group(3)}", redacted)
    redacted = redacted.replace(_AUTH_REDACTION_SENTINEL, "[redacted authorization]")
    if len(redacted) > MAX_PERSISTED_STRING:
        return redacted[:MAX_PERSISTED_STRING] + f"… [truncated {len(redacted) - MAX_PERSISTED_STRING} chars]"
    return redacted


def sanitize_for_persistence(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded, secret-redacted representation safe for local logs/audits.

    This is intentionally conservative: persistent diagnostics should retain
    structure and useful non-secret values, not raw credentials or unbounded
    third-party payloads. Authorization material is removed even when it is
    embedded inside exception text instead of occupying the whole string.
    """
    if depth >= MAX_DEPTH:
        return "[max depth reached]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, bytes):
        return f"[binary omitted: {len(value)} bytes]"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        items = list(value.items())
        for raw_key, raw_value in items[:MAX_COLLECTION_ITEMS]:
            key = str(raw_key)[:300]
            output[key] = "[redacted]" if _sensitive_key(key) else sanitize_for_persistence(raw_value, depth=depth + 1)
        if len(items) > MAX_COLLECTION_ITEMS:
            output["[truncated]"] = f"{len(items) - MAX_COLLECTION_ITEMS} additional keys omitted"
        return output
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized = [sanitize_for_persistence(item, depth=depth + 1) for item in items[:MAX_COLLECTION_ITEMS]]
        if len(items) > MAX_COLLECTION_ITEMS:
            sanitized.append(f"[truncated {len(items) - MAX_COLLECTION_ITEMS} additional items]")
        return sanitized
    text = str(value)
    return sanitize_for_persistence(text, depth=depth + 1)
