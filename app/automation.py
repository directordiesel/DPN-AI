from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import Database, utc_now
from app.persistence_security import sanitize_for_persistence


_AUTOMATION_TIMEOUT_SECONDS = 3600
_STALE_RUNNING_AFTER = timedelta(minutes=90)


class AutomationEngine:
    """Small local scheduler with persisted, single-winner automation claims."""

    def __init__(self, db: Database, agent: Any):
        self.db = db
        self.agent = agent
        self._task: asyncio.Task[Any] | None = None
        self._stopping = asyncio.Event()
        self._running_ids: set[str] = set()

    @staticmethod
    def _next_run(schedule_type: str, schedule_value: str, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        if schedule_type == "interval":
            try:
                minutes = max(1, min(int(schedule_value), 10080))
            except ValueError as exc:
                raise ValueError("Interval schedule value must be whole minutes") from exc
            return now + timedelta(minutes=minutes)
        if schedule_type == "daily":
            try:
                hour_text, minute_text = schedule_value.split(":", 1)
                hour = int(hour_text)
                minute = int(minute_text)
                if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                    raise ValueError
            except ValueError as exc:
                raise ValueError("Daily schedule value must be HH:MM in local system time") from exc
            local_now = datetime.now().astimezone()
            candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= local_now:
                candidate += timedelta(days=1)
            return candidate.astimezone(timezone.utc)
        raise ValueError("Unsupported schedule type")

    def validate(self, schedule_type: str, schedule_value: str) -> str:
        return self._next_run(schedule_type, schedule_value).isoformat()

    def _recover_stale_claims(self, now: datetime) -> int:
        cutoff = (now - _STALE_RUNNING_AFTER).isoformat()
        with self.db.connect() as connection:
            cursor = connection.execute(
                """UPDATE automations
                   SET last_status='failed',
                       last_result='Recovered stale automation execution claim',
                       next_run_at=?, updated_at=?
                   WHERE last_status='running' AND last_run_at IS NOT NULL AND last_run_at < ?""",
                (now.isoformat(), utc_now(), cutoff),
            )
            return int(cursor.rowcount or 0)

    def _claim(self, automation_id: str, started: datetime) -> bool:
        """Atomically claim an automation across workers/processes sharing SQLite."""
        with self.db.connect() as connection:
            cursor = connection.execute(
                """UPDATE automations
                   SET last_status='running', last_run_at=?, updated_at=?
                   WHERE id=? AND COALESCE(last_status,'')!='running'""",
                (started.isoformat(), utc_now(), automation_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _safe_text(value: Any, limit: int = 20_000) -> str:
        sanitized = sanitize_for_persistence(value)
        return str(sanitized)[:limit]

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="dpn-ai-automation-engine")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001
                safe_error = self._safe_text(f"{type(exc).__name__}: {exc}")
                self.db.audit("automation.engine_error", f"Automation engine error: {safe_error}")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=30)
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        self._recover_stale_claims(now)
        enabled = self.db.get_setting("allow_automations", self.agent.settings.allow_automations_default)
        if not enabled:
            return
        for automation in self.db.list_automations():
            if not automation["enabled"] or automation["id"] in self._running_ids:
                continue
            try:
                self._next_run(automation["schedule_type"], automation["schedule_value"], now)
            except ValueError as exc:
                self.db.update_automation(
                    automation["id"],
                    {"last_status": "failed", "last_result": self._safe_text(exc), "next_run_at": None},
                )
                continue
            next_run_raw = automation.get("next_run_at")
            if not next_run_raw:
                next_run = self._next_run(automation["schedule_type"], automation["schedule_value"], now)
                self.db.update_automation(automation["id"], {"next_run_at": next_run.isoformat()})
                continue
            try:
                next_run = datetime.fromisoformat(next_run_raw)
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)
                else:
                    next_run = next_run.astimezone(timezone.utc)
            except (TypeError, ValueError):
                next_run = now
            if next_run <= now:
                asyncio.create_task(self.run_now(automation["id"]), name=f"automation-{automation['id']}")

    async def run_now(self, automation_id: str) -> dict[str, Any]:
        automation = self.db.get_automation(automation_id)
        if not automation:
            return {"ok": False, "error": "Automation not found"}
        if automation_id in self._running_ids:
            return {"ok": False, "error": "Automation is already running"}
        try:
            self._next_run(automation["schedule_type"], automation["schedule_value"])
        except ValueError as exc:
            self.db.update_automation(
                automation_id,
                {"last_status": "failed", "last_result": self._safe_text(exc), "next_run_at": None},
            )
            return {"ok": False, "error": str(exc)}

        started = datetime.now(timezone.utc)
        if not self._claim(automation_id, started):
            return {"ok": False, "error": "Automation is already running"}
        self._running_ids.add(automation_id)
        try:
            result = await asyncio.wait_for(
                self.agent.run(
                    conversation_id=None,
                    user_message=automation["prompt"],
                    profile=automation["profile"],
                    project_id=automation.get("project_id"),
                    source="automation",
                ),
                timeout=_AUTOMATION_TIMEOUT_SECONDS,
            )
            next_run = self._next_run(automation["schedule_type"], automation["schedule_value"], started)
            self.db.update_automation(
                automation_id,
                {
                    "last_run_at": started.isoformat(),
                    "next_run_at": next_run.isoformat(),
                    "last_status": "completed",
                    "last_result": self._safe_text(result.message),
                },
            )
            self.db.audit(
                "automation.completed",
                f"Completed automation {automation['name']}",
                {"automation_id": automation_id, "conversation_id": result.conversation_id},
            )
            return {"ok": True, "conversation_id": result.conversation_id, "run_id": result.run_id, "message": result.message}
        except asyncio.TimeoutError:
            next_run = self._next_run(automation["schedule_type"], automation["schedule_value"], started)
            message = f"Automation exceeded {_AUTOMATION_TIMEOUT_SECONDS} seconds"
            self.db.update_automation(
                automation_id,
                {
                    "last_run_at": started.isoformat(),
                    "next_run_at": next_run.isoformat(),
                    "last_status": "failed",
                    "last_result": message,
                },
            )
            self.db.audit("automation.failed", f"Automation {automation['name']} timed out", {"automation_id": automation_id})
            return {"ok": False, "error": message}
        except Exception as exc:  # noqa: BLE001
            next_run = self._next_run(automation["schedule_type"], automation["schedule_value"], started)
            safe_error = self._safe_text(f"{type(exc).__name__}: {exc}")
            self.db.update_automation(
                automation_id,
                {
                    "last_run_at": started.isoformat(),
                    "next_run_at": next_run.isoformat(),
                    "last_status": "failed",
                    "last_result": safe_error,
                },
            )
            self.db.audit(
                "automation.failed",
                f"Automation {automation['name']} failed",
                {"automation_id": automation_id, "error": safe_error},
            )
            return {"ok": False, "error": safe_error}
        finally:
            self._running_ids.discard(automation_id)
