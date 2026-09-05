"""DPN AI v8 desktop service facade.

This module reuses the existing unified FastAPI application, database, tools, model
runtime, automation engine, and agent state. It adds desktop-specific versioned
read models, an SSE stream, and the Mobile v1 device authentication/pairing adapter
without creating a second AI runtime.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.main import app, db, agent
from mobile.auth_boundary import MobileDeviceAuthBoundary
from mobile.device_registry import DeviceRegistryError
from mobile.pairing import PairingError
from mobile.pairing_service import MobilePairingService


DESKTOP_API_VERSION = "v1"
_mobile_auth = MobileDeviceAuthBoundary(db)
_mobile_pairing = MobilePairingService(_mobile_auth)


class MobilePairingCompleteRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    secret: str = Field(min_length=1, max_length=256)
    device_id: str = Field(min_length=1, max_length=128)
    device_name: str = Field(min_length=1, max_length=80)


def _count_status(items: list[dict[str, Any]], status: str) -> int:
    return sum(str(item.get("status", "")).lower() == status.lower() for item in items)


def _replace_header(scope: dict[str, Any], name: bytes, value: bytes | None) -> None:
    lowered = name.lower()
    headers = [(key, item) for key, item in scope.get("headers", []) if key.lower() != lowered]
    if value is not None:
        headers.append((name, value))
    scope["headers"] = headers


@app.middleware("http")
async def mobile_device_access_boundary(request: Request, call_next):
    """Validate device-scoped mobile credentials before the existing API boundary.

    Android never receives the desktop-wide access token. A request that declares a
    mobile device must first pass the persistent device registry. Only then is the
    request translated into an internal trusted call so app.main's existing API
    boundary remains the single downstream authorization gate.

    The one unauthenticated transport surface is the exact non-``/api`` pairing
    completion route. It is authenticated by a short-lived, one-time high-entropy
    pairing proof and exposes no general runtime API access.
    """
    path = request.url.path
    device_id = request.headers.get("X-DPN-Device-ID", "").strip()
    if path.startswith("/api") and device_id:
        credential = request.headers.get("X-DPN-Token", "")
        try:
            identity = _mobile_auth.authenticate(device_id=device_id, credential=credential)
        except DeviceRegistryError:
            return JSONResponse(status_code=401, content={"detail": "Mobile device credential rejected."})

        request.state.mobile_device = identity
        if settings.access_token:
            _replace_header(request.scope, b"x-dpn-token", settings.access_token.encode("utf-8"))
        else:
            # The mobile credential is the authenticated boundary. For a local-only
            # desktop configuration, present the validated call to the existing
            # loopback-only API gate as internal traffic rather than weakening it.
            request.scope["client"] = ("127.0.0.1", 0)
            _replace_header(request.scope, b"x-dpn-token", None)

    return await call_next(request)


def desktop_summary() -> dict[str, Any]:
    """Return a bounded desktop read model from the unified runtime."""
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


@app.post("/api/v1/mobile/pairing/challenge")
def create_mobile_pairing_challenge() -> dict[str, Any]:
    """Create a short-lived pairing proof from the already-protected desktop API."""
    _mobile_pairing.purge_expired_challenges()
    return _mobile_pairing.create_challenge()


@app.post("/mobile/v1/pairing/complete")
def complete_mobile_pairing(payload: MobilePairingCompleteRequest) -> dict[str, Any]:
    """Exchange one valid pairing proof for one device-scoped credential.

    This route intentionally lives outside ``/api`` so an unpaired Android device
    never needs the desktop-wide API token. The one-time pairing proof is the only
    authority accepted here. No other runtime operation is exposed on this surface.
    """
    try:
        return _mobile_pairing.complete_pairing(
            challenge_id=payload.challenge_id,
            secret=payload.secret,
            device_id=payload.device_id,
            device_name=payload.device_name,
        )
    except PairingError as exc:
        raise HTTPException(status_code=401, detail="Pairing proof rejected or expired.") from exc
    except DeviceRegistryError as exc:
        raise HTTPException(status_code=409, detail="Pairing could not register this device.") from exc


@app.get("/api/v1/mobile/devices")
def list_mobile_devices() -> dict[str, Any]:
    """Return only secret-free paired-device metadata to the protected desktop API."""
    return {"devices": _mobile_pairing.list_devices()}


@app.post("/api/v1/mobile/devices/{device_id}/revoke")
def revoke_mobile_device(device_id: str) -> dict[str, Any]:
    """Persistently revoke a device; subsequent API calls fail at middleware."""
    clean_id = device_id.strip()
    if not clean_id or len(clean_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid device identifier.")
    return {"device_id": clean_id, "revoked": _mobile_pairing.revoke_device(clean_id)}


async def _desktop_event_stream(request: Request) -> AsyncIterator[str]:
    sequence = 0
    while not await request.is_disconnected():
        sequence += 1
        payload = json.dumps(desktop_summary(), sort_keys=True, separators=(",", ":"))
        yield f"id: {sequence}\nevent: desktop.summary\ndata: {payload}\n\n"
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


def _keep_static_mount_last() -> None:
    """Ensure the existing catch-all UI mount cannot shadow v8/mobile routes."""
    static_routes = [route for route in app.router.routes if getattr(route, "name", None) == "static"]
    if not static_routes:
        return
    for route in static_routes:
        app.router.routes.remove(route)
    app.router.routes.extend(static_routes)


_keep_static_mount_last()


__all__ = ["app", "desktop_summary", "DESKTOP_API_VERSION"]
