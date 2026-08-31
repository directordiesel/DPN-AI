from __future__ import annotations

import asyncio
from typing import Any

from app.db import Database


class JobSupervisor:
    """Persistent local background queue for long DPN AI operations.

    Jobs run only while the application is open. Queued and interrupted jobs
    are recovered after restart. Cancellation is cooperative through asyncio.
    """

    def __init__(self, db: Database, agent: Any, orchestrator: Any, workflows: Any, max_concurrency: int = 2):
        self.db = db
        self.agent = agent
        self.orchestrator = orchestrator
        self.workflows = workflows
        self.max_concurrency = max(1, min(int(max_concurrency), 8))
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: list[asyncio.Task[Any]] = []
        self.active: dict[str, asyncio.Task[Any]] = {}
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self.db.requeue_interrupted_jobs()
        for job in reversed(self.db.list_background_jobs("queued", 1000)):
            await self.queue.put(job["id"])
        if not self.workers:
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
        job = self.db.create_background_job(kind, payload)
        await self.queue.put(job["id"])
        self.db.audit("job.queued", f"Queued {kind} job", {"job_id": job["id"]})
        return {"ok": True, "job": job}

    async def _worker(self, _: int) -> None:
        while not self._stopping:
            job_id = await self.queue.get()
            try:
                job = self.db.get_background_job(job_id)
                if not job or job.get("status") != "queued":
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
        self.db.update_background_job(job_id, "running", {"stage": "starting"})
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
                result = await self.workflows.run(
                    str(payload.get("workflow_id") or ""), payload.get("inputs") or {}, payload.get("permissions") or {},
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
            self.db.update_background_job(job_id, "cancelled", {"stage": "cancelled"}, error="Cancelled by operator or application shutdown")
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
        else:
            self.db.update_background_job(job_id, "cancelled", {"stage": "cancelled"}, error="Cancelled before execution")
        return {"ok": True, "job": self.db.get_background_job(job_id)}

    async def retry(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_background_job(job_id)
        if not job:
            return {"ok": False, "error": "Job not found"}
        return await self.submit(job["kind"], job.get("payload") or {})