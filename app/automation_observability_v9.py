from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable


MAX_HISTORY_RECORDS = 10_000
MAX_NOTIFICATION_PROVIDERS = 32
_ALLOWED_STATUSES = {"completed", "failed", "cancelled", "skipped"}


class AutomationObservabilityError(ValueError):
    """Raised when automation history or notification contracts fail closed."""


@dataclass(frozen=True)
class AutomationRunRecord:
    automation_id: str
    run_id: str
    status: str
    started_at: str
    finished_at: str
    attempt: int = 1
    evidence_count: int = 0

    def validate(self) -> None:
        if not str(self.automation_id or "").strip() or len(self.automation_id) > 128:
            raise AutomationObservabilityError("automation_id is invalid")
        if not str(self.run_id or "").strip() or len(self.run_id) > 128:
            raise AutomationObservabilityError("run_id is invalid")
        if self.status not in _ALLOWED_STATUSES:
            raise AutomationObservabilityError("automation run status is invalid")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or not 1 <= self.attempt <= 100:
            raise AutomationObservabilityError("attempt must be between 1 and 100")
        if isinstance(self.evidence_count, bool) or not isinstance(self.evidence_count, int) or self.evidence_count < 0:
            raise AutomationObservabilityError("evidence_count must be a non-negative integer")
        try:
            started = datetime.fromisoformat(self.started_at)
            finished = datetime.fromisoformat(self.finished_at)
        except (TypeError, ValueError) as exc:
            raise AutomationObservabilityError("automation history timestamps are invalid") from exc
        if started.tzinfo is None or finished.tzinfo is None:
            raise AutomationObservabilityError("automation history timestamps must be timezone-aware")
        if finished.astimezone(timezone.utc) < started.astimezone(timezone.utc):
            raise AutomationObservabilityError("automation run cannot finish before it starts")


class AutomationHistoryBuffer:
    """Bounded, payload-free run history for operator diagnostics."""

    def __init__(self, *, max_records: int = 500) -> None:
        if isinstance(max_records, bool) or not isinstance(max_records, int):
            raise AutomationObservabilityError("max_records must be an integer")
        if not 1 <= max_records <= MAX_HISTORY_RECORDS:
            raise AutomationObservabilityError(f"max_records must be between 1 and {MAX_HISTORY_RECORDS}")
        self.max_records = max_records
        self._records: deque[AutomationRunRecord] = deque(maxlen=max_records)

    def append(self, record: AutomationRunRecord) -> AutomationRunRecord:
        if not isinstance(record, AutomationRunRecord):
            raise AutomationObservabilityError("history entry must be AutomationRunRecord")
        record.validate()
        self._records.append(record)
        return record

    def list(self, *, automation_id: str | None = None, limit: int = 100) -> tuple[AutomationRunRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.max_records:
            raise AutomationObservabilityError("history limit is invalid")
        values: Iterable[AutomationRunRecord] = reversed(self._records)
        if automation_id is not None:
            wanted = str(automation_id).strip()
            if not wanted:
                raise AutomationObservabilityError("automation_id filter is invalid")
            values = (item for item in values if item.automation_id == wanted)
        result: list[AutomationRunRecord] = []
        for item in values:
            result.append(item)
            if len(result) >= limit:
                break
        return tuple(result)

    def status(self) -> dict[str, int]:
        return {"records": len(self._records), "capacity": self.max_records}


@dataclass(frozen=True)
class NotificationProviderSpec:
    key: str
    configured: bool = False
    verified_live: bool = False
    supports: tuple[str, ...] = ("completed", "failed")

    def validate(self) -> None:
        key = str(self.key or "").strip().lower()
        if not key or len(key) > 64 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in key):
            raise AutomationObservabilityError("notification provider key is invalid")
        normalized = tuple(dict.fromkeys(str(item).strip().lower() for item in self.supports if str(item).strip()))
        if not normalized or any(item not in _ALLOWED_STATUSES for item in normalized):
            raise AutomationObservabilityError("notification provider statuses are invalid")
        if self.verified_live and not self.configured:
            raise AutomationObservabilityError("notification provider cannot be live unless configured")


class NotificationProviderRegistry:
    """Transport-neutral notification readiness registry.

    Registration never performs I/O. A provider is dispatch-eligible only when
    configuration and a trusted external health check both explicitly mark it live.
    """

    def __init__(self) -> None:
        self._providers: dict[str, NotificationProviderSpec] = {}

    def register(self, spec: NotificationProviderSpec) -> None:
        if not isinstance(spec, NotificationProviderSpec):
            raise AutomationObservabilityError("provider must be NotificationProviderSpec")
        spec.validate()
        key = spec.key.strip().lower()
        if key in self._providers:
            raise AutomationObservabilityError(f"notification provider already registered: {key}")
        if len(self._providers) >= MAX_NOTIFICATION_PROVIDERS:
            raise AutomationObservabilityError("notification provider registry is full")
        self._providers[key] = NotificationProviderSpec(
            key=key,
            configured=bool(spec.configured),
            verified_live=bool(spec.verified_live),
            supports=tuple(dict.fromkeys(item.strip().lower() for item in spec.supports)),
        )

    def readiness(self, key: str) -> dict[str, object]:
        normalized = str(key or "").strip().lower()
        if normalized not in self._providers:
            raise AutomationObservabilityError(f"unknown notification provider: {normalized or '<blank>'}")
        spec = self._providers[normalized]
        return {
            "key": spec.key,
            "configured": spec.configured,
            "live": spec.verified_live,
            "supports": spec.supports,
        }

    def dispatch_plan(self, *, key: str, record: AutomationRunRecord) -> dict[str, object]:
        if not isinstance(record, AutomationRunRecord):
            raise AutomationObservabilityError("notification record must be AutomationRunRecord")
        record.validate()
        readiness = self.readiness(key)
        if not readiness["configured"]:
            raise AutomationObservabilityError("notification provider is not configured")
        if not readiness["live"]:
            raise AutomationObservabilityError("notification provider is not verified live")
        if record.status not in readiness["supports"]:
            raise AutomationObservabilityError("notification provider does not support this automation status")
        # This is intentionally only a plan: no endpoint, credential, prompt, or
        # provider payload is retained or sent by this contract layer.
        return {
            "ok": True,
            "provider": readiness["key"],
            "automation_id": record.automation_id,
            "run_id": record.run_id,
            "status": record.status,
            "attempt": record.attempt,
        }


def history_payload(records: Iterable[AutomationRunRecord]) -> tuple[dict[str, object], ...]:
    payload: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, AutomationRunRecord):
            raise AutomationObservabilityError("history payload contains an invalid record")
        record.validate()
        payload.append(asdict(record))
    return tuple(payload)


__all__ = [
    "AutomationHistoryBuffer",
    "AutomationObservabilityError",
    "AutomationRunRecord",
    "MAX_HISTORY_RECORDS",
    "MAX_NOTIFICATION_PROVIDERS",
    "NotificationProviderRegistry",
    "NotificationProviderSpec",
    "history_payload",
]
