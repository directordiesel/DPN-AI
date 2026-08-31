from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import Database
from app.job_supervisor import JobSupervisor


class BlockingAgent:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, **kwargs):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(model_dump=lambda: {"ok": True, "message": kwargs.get("user_message", "")})


def _supervisor(tmp_path: Path, agent=None, concurrency: int = 2) -> JobSupervisor:
    db = Database(tmp_path / "data.sqlite3")
    return JobSupervisor(db, agent or BlockingAgent(), SimpleNamespace(), SimpleNamespace(), max_concurrency=concurrency)


def test_atomic_claim_allows_only_one_winner(tmp_path: Path):
    supervisor = _supervisor(tmp_path)
    job = supervisor.db.create_background_job("direct", {"message": "once"})
    assert supervisor._claim_job(job["id"]) is True
    assert supervisor._claim_job(job["id"]) is False
    loaded = supervisor.db.get_background_job(job["id"])
    assert loaded is not None
    assert loaded["status"] == "running"


def test_cancel_queued_job_is_compare_and_set(tmp_path: Path):
    supervisor = _supervisor(tmp_path)
    job = supervisor.db.create_background_job("direct", {"message": "cancel"})
    assert supervisor._cancel_queued_job(job["id"]) is True
    assert supervisor._cancel_queued_job(job["id"]) is False
    loaded = supervisor.db.get_background_job(job["id"])
    assert loaded is not None
    assert loaded["status"] == "cancelled"


@pytest.mark.asyncio
async def test_duplicate_queue_entries_execute_job_once(tmp_path: Path):
    agent = BlockingAgent()
    supervisor = _supervisor(tmp_path, agent=agent, concurrency=2)
    job = supervisor.db.create_background_job("direct", {"message": "once"})
    await supervisor.queue.put(job["id"])
    await supervisor.queue.put(job["id"])
    supervisor.workers = [
        asyncio.create_task(supervisor._worker(0)),
        asyncio.create_task(supervisor._worker(1)),
    ]
    try:
        await asyncio.wait_for(agent.started.wait(), timeout=2)
        await asyncio.sleep(0.05)
        assert agent.calls == 1
        agent.release.set()
        await asyncio.wait_for(supervisor.queue.join(), timeout=2)
        loaded = supervisor.db.get_background_job(job["id"])
        assert loaded is not None
        assert loaded["status"] == "completed"
    finally:
        await supervisor.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent_while_workers_are_running(tmp_path: Path):
    supervisor = _supervisor(tmp_path, concurrency=1)
    job = supervisor.db.create_background_job("direct", {"message": "pending"})
    await supervisor.start()
    first_workers = list(supervisor.workers)
    queued_after_first_start = supervisor.queue.qsize()
    await supervisor.start()
    assert supervisor.workers == first_workers
    assert supervisor.queue.qsize() <= queued_after_first_start
    await supervisor.stop()
    loaded = supervisor.db.get_background_job(job["id"])
    assert loaded is not None
    assert loaded["status"] in {"queued", "cancelled"}


@pytest.mark.asyncio
async def test_shutdown_pauses_running_job_for_restart(tmp_path: Path):
    agent = BlockingAgent()
    supervisor = _supervisor(tmp_path, agent=agent, concurrency=1)
    submitted = await supervisor.submit("direct", {"message": "resume later"})
    await supervisor.start()
    await asyncio.wait_for(agent.started.wait(), timeout=2)
    await supervisor.stop()
    loaded = supervisor.db.get_background_job(submitted["job"]["id"])
    assert loaded is not None
    assert loaded["status"] == "queued"
    assert "shutdown" in loaded["error_text"].lower()


@pytest.mark.asyncio
async def test_retry_requires_terminal_retryable_state(tmp_path: Path):
    supervisor = _supervisor(tmp_path)
    queued = supervisor.db.create_background_job("direct", {"message": "queued"})
    rejected = await supervisor.retry(queued["id"])
    assert rejected["ok"] is False
    assert "failed or cancelled" in rejected["error"].lower()

    supervisor.db.update_background_job(queued["id"], "failed", error="test failure")
    retried = await supervisor.retry(queued["id"])
    assert retried["ok"] is True
    assert retried["job"]["id"] != queued["id"]
    assert retried["job"]["status"] == "queued"
