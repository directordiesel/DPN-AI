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


def _supervisor(tmp_path: Path, agent=None, concurrency: int = 2, queue_depth: int = 1000) -> JobSupervisor:
    db = Database(tmp_path / "data.sqlite3")
    return JobSupervisor(
        db,
        agent or BlockingAgent(),
        SimpleNamespace(),
        SimpleNamespace(),
        max_concurrency=concurrency,
        max_queue_depth=queue_depth,
    )


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


@pytest.mark.asyncio
async def test_submit_fails_fast_when_queue_is_at_capacity(tmp_path: Path):
    supervisor = _supervisor(tmp_path, queue_depth=1)
    first = await supervisor.submit("direct", {"message": "one"})
    assert first["ok"] is True
    second = await supervisor.submit("direct", {"message": "two"})
    assert second["ok"] is False
    assert "capacity" in second["error"].lower()
    assert second["queue"] == {"depth": 1, "capacity": 1}
    queued = supervisor.db.list_background_jobs("queued", 10)
    assert len(queued) == 1


def test_queue_depth_is_bounded_and_status_is_secret_free(tmp_path: Path):
    supervisor = _supervisor(tmp_path, concurrency=99, queue_depth=50_000)
    assert supervisor.max_concurrency == 8
    assert supervisor.max_queue_depth == 10_000
    assert supervisor.queue.maxsize == 10_000
    assert supervisor.queue_status() == {"depth": 0, "capacity": 10_000, "active": 0, "workers": 0}


def test_non_integer_queue_depth_is_rejected(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    with pytest.raises(ValueError, match="max_queue_depth"):
        JobSupervisor(db, BlockingAgent(), SimpleNamespace(), SimpleNamespace(), max_queue_depth=True)
