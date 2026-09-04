"""DPN AI v8 desktop service facade.

This module reuses the existing unified FastAPI application, database, tools, model
runtime, automation engine, and agent state. It adds only desktop-specific,
versioned read models and an SSE stream; it does not create a second AI runtime.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.main import app, db, agent


DESKTOP_API_VERSION = "v1"


def _count_status(items: list[dict[str, Any]], status: str) -> int:
    return sum(str(item.get("status", "")).lower() == status.lower() for item in items)


def desktop_summary() -> dict[str, Any]:
    """Return a bounded, secret-free desktop read model from the unified runtime."""
    missions = db.list_missions(limit=1000)
    approvals = db.list_approvals("pending", 1000)
    automations = db.list_automations()
    connectors = db.list_connectors()
    jobs = db.list_background_jobs(limit=1000)
    effective = agent.effective_settings()

    return {
        "api_version": DESKTOP_API_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "status": "online",
            "mode": effective.get("intelligence_mode", "maximum"),
        },
        "missions": {
            "total": len(missions),
            "running": _count_status(missions, "running"),
            "queued": _count_status(missions, "queued"),
            "failed": _count_status(missions, "failed"),
        },
        "approvals": {"pending": len(approvals)},
        "model": {
            "active": db.get_setting("active_intelligence_model", "warming"),
            "warm_status": db.get_setting("intelligence_warm_status", {"ok": False, "status": "starting"}),
        },
        "automations": {
            "total": len(automations),
            "enabled": sum(bool(item.get("enabled")) for item in automations),
        },
        "connectors": {
            "total": len(connectors),
            "enabled": sum(bool(item.get("enabled", True)) for item in connectors),
        },
        "jobs": {
            "total": len(jobs),
            "running": _count_status(jobs, "running"),
            "queued": _count_status(jobs, "queued"),
            "failed": _count_status(jobs, "failed"),
        },
    }


@app.get("/api/v1/desktop/summary")
def get_desktop_summary() -> dict[str, Any]:
    return desktop_summary()


async def _desktop_event_stream(request: Request) -> AsyncIterator[str]:
    last_payload = ""
    sequence = 0
    while not await request.is_disconnected():
        payload = json.dumps(desktop_summary(), sort_keys=True, separators=(",", ":"))
        if payload != last_payload:
            sequence += 1
            yield f"id: {sequence}\nevent: desktop.summary\ndata: {payload}\n\n"
            last_payload = payload
        else:
            yield ": keepalive\n\n"
        await asyncio.sleep(2.0)


@app.get("/api/v1/desktop/events")
async def desktop_events(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _desktop_event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["app", "desktop_summary", "DESKTOP_API_VERSION"]
