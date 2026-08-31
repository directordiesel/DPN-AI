from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.automation import AutomationEngine
from app.db import Database


class RecordingAgent:
    def __init__(self, *, delay: float = 0.0, fail: bool = False):
        self.settings = SimpleNamespace(allow_automations_default=True)
        self.delay = delay
        self.fail = fail
        self.calls = 0

    async def run(self, **kwargs):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("Bearer super-secret-token")
        return SimpleNamespace(
            message="completed",
            conversation_id="conversation-1",
            run_id="run-1",
        )


def create_automation(db: Database, *, schedule_type: str = "interval", schedule_value: str = "5") -> dict:
    return db.create_automation(
        {
            "name": "Security test",
            "prompt": "perform the task",
            "schedule_type": schedule_type,
            "schedule_value": schedule_value,
            "profile": "auto",
            "enabled": True,
        }
    )


@pytest.mark.asyncio
async def test_automation_claim_is_single_winner_across_engines(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    automation = create_automation(db)
    agent = RecordingAgent(delay=0.05)
    first = AutomationEngine(db, agent)
    second = AutomationEngine(db, agent)

    results = await asyncio.gather(
        first.run_now(automation["id"]),
        second.run_now(automation["id"]),
    )

    assert agent.calls == 1
    assert sum(1 for result in results if result.get("ok")) == 1
    assert sum(1 for result in results if result.get("error") == "Automation is already running") == 1


@pytest.mark.asyncio
async def test_automation_failure_redacts_bearer_secret_from_persistence(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    automation = create_automation(db)
    engine = AutomationEngine(db, RecordingAgent(fail=True))

    result = await engine.run_now(automation["id"])
    assert not result["ok"]
    stored = db.get_automation(automation["id"])
    assert stored is not None
    persisted = stored.get("last_result") or ""
    assert "super-secret-token" not in persisted
    assert "[redacted authorization]" in persisted


@pytest.mark.asyncio
async def test_invalid_schedule_fails_without_agent_execution(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    automation = create_automation(db, schedule_type="daily", schedule_value="99:99")
    agent = RecordingAgent()
    engine = AutomationEngine(db, agent)

    result = await engine.run_now(automation["id"])

    assert not result["ok"]
    assert agent.calls == 0
    stored = db.get_automation(automation["id"])
    assert stored is not None
    assert stored["last_status"] == "failed"


def test_stale_running_claim_is_recovered(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    automation = create_automation(db)
    with db.connect() as connection:
        connection.execute(
            "UPDATE automations SET last_status='running',last_run_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (automation["id"],),
        )

    engine = AutomationEngine(db, RecordingAgent())
    recovered = engine._recover_stale_claims(__import__("datetime").datetime.now(__import__("datetime").timezone.utc))

    assert recovered == 1
    stored = db.get_automation(automation["id"])
    assert stored is not None
    assert stored["last_status"] == "failed"
    assert "Recovered stale" in stored["last_result"]
