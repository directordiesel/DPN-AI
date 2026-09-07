from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable


class ProactiveSourceError(ValueError):
    """Raised when a trusted condition source cannot produce safe evidence."""


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    max_age_seconds: int = 300
    trusted_for_dispatch: bool = True

    def validate(self) -> None:
        source_id = self.source_id.strip()
        if not source_id or len(source_id) > 120:
            raise ProactiveSourceError("source_id must be 1-120 characters")
        if isinstance(self.max_age_seconds, bool) or not isinstance(self.max_age_seconds, int):
            raise ProactiveSourceError("max_age_seconds must be an integer")
        if not 1 <= self.max_age_seconds <= 86_400:
            raise ProactiveSourceError("max_age_seconds must be between 1 and 86400")


@dataclass(frozen=True)
class ObservationEvidence:
    source_id: str
    value: Any
    observed_at: float
    collected_at: float
    expires_at: float
    source_digest: str
    trusted_for_dispatch: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def require_fresh(self, now: float) -> None:
        if not math.isfinite(now) or now < 0:
            raise ProactiveSourceError("clock returned an invalid timestamp")
        if now > self.expires_at:
            raise ProactiveSourceError("condition source evidence is stale")
        if self.observed_at > now + 5:
            raise ProactiveSourceError("condition source observation timestamp is in the future")


@dataclass(frozen=True)
class _RegisteredSource:
    contract: SourceContract
    collector: Callable[[], Any]


class ProactiveSourceRegistry:
    """Host-owned source registry for proactive observations.

    Only application/plugin initialization receives ``register_source``. Model-visible
    tools may collect a named source but cannot create or upgrade a source to trusted.
    """

    def __init__(self, *, clock=time.time) -> None:
        self._clock = clock
        self._sources: dict[str, _RegisteredSource] = {}

    def register_source(self, contract: SourceContract, collector: Callable[[], Any]) -> None:
        contract.validate()
        source_id = contract.source_id.strip()
        if source_id in self._sources:
            raise ProactiveSourceError("source_id is already registered")
        if not callable(collector):
            raise ProactiveSourceError("source collector must be callable")
        self._sources[source_id] = _RegisteredSource(contract=contract, collector=collector)

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": item.contract.source_id,
                "max_age_seconds": item.contract.max_age_seconds,
                "trusted_for_dispatch": item.contract.trusted_for_dispatch,
            }
            for item in self._sources.values()
        ]

    def collect(self, source_id: str) -> ObservationEvidence:
        registered = self._sources.get(str(source_id).strip())
        if registered is None:
            raise ProactiveSourceError("condition source is not registered by the host")
        now = float(self._clock())
        if not math.isfinite(now) or now < 0:
            raise ProactiveSourceError("clock returned an invalid timestamp")
        raw = registered.collector()
        observed_at = now
        value = raw
        if isinstance(raw, tuple) and len(raw) == 2:
            value, observed_at = raw
        try:
            observed_at = float(observed_at)
        except (TypeError, ValueError) as exc:
            raise ProactiveSourceError("source observation timestamp is invalid") from exc
        if not math.isfinite(observed_at) or observed_at < 0 or observed_at > now + 5:
            raise ProactiveSourceError("source observation timestamp is invalid")
        try:
            canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ProactiveSourceError("source value must be finite JSON data") from exc
        digest_seed = json.dumps(
            {"source_id": registered.contract.source_id, "observed_at": observed_at, "value": json.loads(canonical)},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(digest_seed.encode("utf-8")).hexdigest()
        evidence = ObservationEvidence(
            source_id=registered.contract.source_id,
            value=json.loads(canonical),
            observed_at=observed_at,
            collected_at=now,
            expires_at=observed_at + registered.contract.max_age_seconds,
            source_digest=digest,
            trusted_for_dispatch=registered.contract.trusted_for_dispatch,
        )
        evidence.require_fresh(now)
        return evidence


__all__ = [
    "ObservationEvidence",
    "ProactiveSourceError",
    "ProactiveSourceRegistry",
    "SourceContract",
]
