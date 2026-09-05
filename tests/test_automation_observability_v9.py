from datetime import datetime, timedelta, timezone

import pytest

from app.automation_observability_v9 import (
    AutomationHistoryBuffer,
    AutomationObservabilityError,
    AutomationRunRecord,
    MAX_HISTORY_RECORDS,
    NotificationProviderRegistry,
    NotificationProviderSpec,
    history_payload,
)


def _record(index: int, *, status: str = "completed", automation_id: str = "auto-1") -> AutomationRunRecord:
    started = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    return AutomationRunRecord(
        automation_id=automation_id,
        run_id=f"run-{index}",
        status=status,
        started_at=started.isoformat(),
        finished_at=(started + timedelta(seconds=5)).isoformat(),
        attempt=1,
        evidence_count=index,
    )


def test_history_is_bounded_and_returns_newest_first():
    history = AutomationHistoryBuffer(max_records=2)
    history.append(_record(1))
    history.append(_record(2))
    history.append(_record(3))
    assert [item.run_id for item in history.list(limit=2)] == ["run-3", "run-2"]
    assert history.status() == {"records": 2, "capacity": 2}


def test_history_filter_preserves_project_automation_isolation():
    history = AutomationHistoryBuffer(max_records=4)
    history.append(_record(1, automation_id="alpha"))
    history.append(_record(2, automation_id="beta"))
    history.append(_record(3, automation_id="alpha"))
    assert [item.run_id for item in history.list(automation_id="alpha", limit=2)] == ["run-3", "run-1"]


def test_history_rejects_bad_chronology_and_unbounded_limits():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bad = AutomationRunRecord(
        automation_id="a",
        run_id="r",
        status="failed",
        started_at=started.isoformat(),
        finished_at=(started - timedelta(seconds=1)).isoformat(),
    )
    with pytest.raises(AutomationObservabilityError, match="finish before"):
        AutomationHistoryBuffer().append(bad)
    with pytest.raises(AutomationObservabilityError, match="max_records"):
        AutomationHistoryBuffer(max_records=MAX_HISTORY_RECORDS + 1)


def test_history_payload_contains_no_prompt_or_provider_secret_fields():
    payload = history_payload((_record(1),))[0]
    assert set(payload) == {
        "automation_id",
        "run_id",
        "status",
        "started_at",
        "finished_at",
        "attempt",
        "evidence_count",
    }
    text = str(payload).lower()
    assert "prompt" not in text
    assert "secret" not in text
    assert "token" not in text


def test_notification_registry_fails_closed_until_verified_live():
    registry = NotificationProviderRegistry()
    registry.register(NotificationProviderSpec(key="desktop", configured=True, verified_live=False))
    assert registry.readiness("desktop") == {
        "key": "desktop",
        "configured": True,
        "live": False,
        "supports": ("completed", "failed"),
    }
    with pytest.raises(AutomationObservabilityError, match="not verified live"):
        registry.dispatch_plan(key="desktop", record=_record(1))


def test_notification_provider_cannot_claim_live_without_configuration():
    with pytest.raises(AutomationObservabilityError, match="unless configured"):
        NotificationProviderSpec(key="email", configured=False, verified_live=True).validate()


def test_dispatch_plan_is_transport_neutral_and_payload_free():
    registry = NotificationProviderRegistry()
    registry.register(
        NotificationProviderSpec(
            key="desktop",
            configured=True,
            verified_live=True,
            supports=("completed", "failed"),
        )
    )
    plan = registry.dispatch_plan(key="desktop", record=_record(5, status="failed"))
    assert plan == {
        "ok": True,
        "provider": "desktop",
        "automation_id": "auto-1",
        "run_id": "run-5",
        "status": "failed",
        "attempt": 1,
    }
    text = str(plan).lower()
    assert "endpoint" not in text
    assert "credential" not in text
    assert "prompt" not in text


def test_notification_status_support_is_enforced():
    registry = NotificationProviderRegistry()
    registry.register(
        NotificationProviderSpec(
            key="audit",
            configured=True,
            verified_live=True,
            supports=("failed",),
        )
    )
    with pytest.raises(AutomationObservabilityError, match="does not support"):
        registry.dispatch_plan(key="audit", record=_record(1, status="completed"))
