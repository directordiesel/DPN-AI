from __future__ import annotations

import asyncio
from typing import Any

from app.db import Database, utc_now


class JobSupervisor:
    """Persistent local background queue for long DPN AI operations.

    Jobs run only while the application is open. Queued and interrupted jobs
    are recovered after restart. Cancellation is cooperative through asyncio.
    Database state transitions are claimed atomically so duplicate queue entries
    or multiple supervisors cannot execute the same queued job concurrently.
    """

    DEFAULT_MAX_QUEUE_DEPTH = 1000

    def __init__(
        self,
        db: Database,
        agent: Any,
        orchestrator: Any,
        workflows: Any,
        max_concurrency: int = 2,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    ):
        self.db = db
        self.agent = agent
        self.orchestrator = orchestrator
        self.workflows = workflows
        self.max_concurrency = max(1, min(int(max_concurrency), 8))
        if isinstance(max_queue_depth, bool) or not isinstance(max_queue_depth, int):
            raise ValueError("max_queue_depth must be an integer")
        self.max_queue_depth = max(1, min(max_queue_depth, 10_000))
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.max_queue_depth)
        self.workers: list[asyncio.Task[Any]] = []
        self.active: dict[str, asyncio.Task[Any]] = {}
        self._stopping = False

    async def start(self) -> None:
        # start() may be called more than once by application lifecycle hooks.
        # Do not enqueue the persistent queue again while workers are alive.
        self.workers = [worker for worker in self.workers if not worker.done()]
        if self.workers:
            return
        self._stopping = False
        self.db.requeue_interrupted_jobs()
        queued_jobs = list(reversed(self.db.list_background_jobs("queued", self.max_queue_depth)))
        for job in queued_jobs:
            try:
                self.queue.put_nowait(job["id"])
            except asyncio.QueueFull:
                break
        self.workers = [asyncio.create_task(self._worker(index), name=f"dpn-job-worker-{index}") for index in range(self.max_concurrency)]

    async def stop(self) -> None:
        self._stopping = True
        for task in list(self.active.values()):
            task.cancel()
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        self.active.clear()

    async def submit(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind not in {"direct", "mission", "workflow"}:
            return {"ok": False, "error": "Job kind must be direct, mission, or workflow"}
        if self.queue.full():
            return {
                "ok": False,
                "error": "Background job queue is at its configured capacity",
                "queue": {"depth": self.queue.qsize(), "capacity": self.max_queue_depth},
            }
        job = self.db.create_background_job(kind, payload)
        try:
            self.queue.put_nowait(job["id"])
        except asyncio.QueueFull:
            # Fail closed without leaving an unreachable persistent job behind.
            self._cancel_queued_job(job["id"])
            return {
                "ok": False,
                "error": "Background job queue reached capacity before admission completed",
                "queue": {"depth": self.queue.qsize(), "capacity": self.max_queue_depth},
            }
        self.db.audit("job.queued", f"Queued {kind} job", {"job_id": job["id"]})
        return {"ok": True, "job": job}

    def queue_status(self) -> dict[str, int]:
        return {
            "depth": self.queue.qsize(),
            "capacity": self.max_queue_depth,
            "active": len(self.active),
            "workers": len([worker for worker in self.workers if not worker.done()]),
        }

    def _claim_job(self, job_id: str) -> bool:
        """Atomically move one queued job to running.

        The conditional UPDATE is the concurrency boundary. Only one worker or
        process can change a given job from queued to running, so duplicate
        queue entries cannot cause duplicate execution.
        """
        now = utc_now()
        with self.db.connect() as db:
            cursor = db.execute(
                """UPDATE background_jobs
                SET status='running', started_at=?, updated_at=?, progress_json='{"stage":"starting"}',
                    completed_at=NULL, error_text=''
                WHERE id=? AND status='queued'""",
                (now, now, job_id),
            )
        return cursor.rowcount == 1

    def _cancel_queued_job(self, job_id: str) -> bool:
        now = utc_now()
        with self.db.connect() as db:
            cursor = db.execute(
                """UPDATE background_jobs
                SET status='cancelled', progress_json='{"stage":"cancelled"}',
                    error_text='Cancelled before execution', completed_at=?, updated_at=?
                WHERE id=? AND status='queued'""",
                (now, now, job_id),
            )
        return cursor.rowcount == 1

    async def _worker(self, _: int) -> None:
        while not self._stopping:
            job_id = await self.queue.get()
            try:
                if not self._claim_job(job_id):
                    continue
                job = self.db.get_background_job(job_id)
                if not job or job.get("status") != "running":
                    continue
                task = asyncio.create_task(self._run_job(job), name=f"dpn-job-{job_id}")
                self.active[job_id] = task
                try:
                    await task
                finally:
                    self.active.pop(job_id, None)
            finally:
                self.queue.task_done()

    async def _run_job(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        payload = job.get("payload") or {}
        try:
            if job["kind"] == "mission":
                self.db.update_background_job(job_id, progress={"stage": "mission", "objective": str(payload.get("objective", ""))[:240]})
                result = await self.orchestrator.run(
                    objective=str(payload.get("objective") or ""),
                    conversation_id=payload.get("conversation_id"), project_id=payload.get("project_id"),
                    attachments=payload.get("attachments") or [], profile=str(payload.get("profile") or "auto"),
                    model=payload.get("model"), think=payload.get("think"), budget=payload.get("budget") or {},
                )
            elif job["kind"] == "workflow":
                self.db.update_background_job(job_id, progress={"stage": "workflow", "workflow_id": payload.get("workflow_id")})
                # Persisted job payloads are data, never authorization. WorkflowEngine
                # re-reads live settings before every tool call, so permissions saved
                # when a job was submitted cannot be replayed after an operator revokes
                # access or switches to Safe approval mode.
                result = await self.workflows.run(
                    str(payload.get("workflow_id") or ""), payload.get("inputs") or {}, None,
                )
            else:
                self.db.update_background_job(job_id, progress={"stage": "direct", "message": str(payload.get("message", ""))[:240]})
                response = await self.agent.run(
                    conversation_id=payload.get("conversation_id"), user_message=str(payload.get("message") or ""),
                    model=payload.get("model"), think=payload.get("think"), attachments=payload.get("attachments") or [],
                    profile=str(payload.get("profile") or "auto"), project_id=payload.get("project_id"),
                    source=f"background:{job_id}", skill_ids=payload.get("skill_ids") or [],
                )
                result = response.model_dump()
            status = "completed" if result.get("ok", True) else "failed"
            self.db.update_background_job(job_id, status, {"stage": "finished"}, result, "" if status == "completed" else str(result.get("error", "Operation reported failure")))
            self.db.audit(f"job.{status}", f"Background job {status}", {"job_id": job_id, "kind": job["kind"]})
        except asyncio.CancelledError:
            if self._stopping:
                # Graceful application shutdown is a pause, not an operator
                # cancellation. Leaving it queued makes restart recovery exact.
                self.db.update_background_job(job_id, "queued", {"stage": "queued"}, error="Paused by application shutdown")
                self.db.audit("job.paused", "Background job paused for application shutdown", {"job_id": job_id})
            else:
                self.db.update_background_job(job_id, "cancelled", {"stage": "cancelled"}, error="Cancelled by operator")
                self.db.audit("job.cancelled", "Background job cancelled by operator", {"job_id": job_id})
            raise
        except Exception as exc:  # noqa: BLE001
            self.db.update_background_job(job_id, "failed", {"stage": "failed"}, error=f"{type(exc).__name__}: {exc}")
            self.db.audit("job.failed", "Background job failed", {"job_id": job_id, "error": str(exc)[:1000]})

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_background_job(job_id)
        if not job:
            return {"ok": False, "error": "Job not found"}
        if job["status"] in {"completed", "failed", "cancelled"}:
            return {"ok": False, "error": f"Job is already {job['status']}"}
        task = self.active.get(job_id)
        if task:
            task.cancel()
        elif not self._cancel_queued_job(job_id):
            # The job may have been atomically claimed between the initial read
            # and this cancellation attempt. Re-check active/state rather than
            # overwriting a running or terminal transition.
            await asyncio.sleep(0)
            task = self.active.get(job_id)
            if task:
                task.cancel()
            else:
                current = self.db.get_background_job(job_id)
                if current and current.get("status") == "running":
                    return {"ok": False, "error": "Job has started and could not be cancelled before execution"}
        return {"ok": True, "job": self.db.get_background_job(job_id)}

    async def retry(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_background_job(job_id)
        if not job:
            return {"ok": False, "error": "Job not found"}
        if job.get("status") not in {"failed", "cancelled"}:
            return {"ok": False, "error": "Only failed or cancelled jobs can be retried"}
        return await self.submit(job["kind"], job.get("payload") or {})
