from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.persistence_security import sanitize_for_persistence


_PREFIX = "approval_payload."
_TERMINAL = {"denied", "executed", "failed"}
_ACTIVE = {"pending", "approved"}
_APPROVAL_TTL = timedelta(hours=24)


def _payload_name(approval_id: str) -> str:
    return f"{_PREFIX}{approval_id}"


def _created_at(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _live_permissions(registry: Any) -> dict[str, Any] | None:
    """Return current authorization gates for the production registry.

    Approval is consent to one operation, not a durable capability token. If an
    operator revokes a gate or switches to Safe mode after approving but before
    execution, the current policy wins. Lightweight test registries without the
    production settings surface return None and keep their isolated test path.
    """
    settings = getattr(registry, "settings", None)
    db = getattr(registry, "db", None)
    if settings is None or db is None or not hasattr(db, "all_settings"):
        return None
    stored = db.all_settings()
    return {
        "allow_commands": bool(stored.get("allow_commands", settings.allow_commands_default)),
        "allow_web": bool(stored.get("allow_web", settings.allow_web_default)),
        "allow_images": bool(stored.get("allow_images", settings.allow_images_default)),
        "allow_browser": bool(stored.get("allow_browser", settings.allow_browser_default)),
        "allow_desktop": bool(stored.get("allow_desktop", settings.allow_desktop_default)),
        "allow_voice": bool(stored.get("allow_voice", settings.allow_voice_default)),
        "allow_connectors": bool(stored.get("allow_connectors", settings.allow_connectors_default)),
        "allow_mcp": bool(stored.get("allow_mcp", settings.allow_mcp_default)),
        "allow_self_improvement": bool(stored.get("allow_self_improvement", settings.allow_self_improvement_default)),
        "approval_mode": str(stored.get("approval_mode", "standard") or "standard"),
    }


def _scrub_legacy_rows(db: Any, vault: Any) -> dict[str, int]:
    """Remove legacy plaintext approval payloads and expire abandoned approvals.

    Older DPN AI builds wrote exact approval arguments into SQLite. On startup,
    rewrite every approval row through the persistence sanitizer. When a rewrite
    is needed, enable SQLite secure-delete and compact the database after the
    transaction so obsolete page content is not intentionally retained.
    """
    now = datetime.now(timezone.utc)
    scrubbed = 0
    expired = 0
    payloads_deleted = 0

    with db.connect() as connection:
        connection.execute("PRAGMA secure_delete=ON")
        rows = connection.execute(
            "SELECT id,status,arguments_json,result_json,created_at FROM approval_requests"
        ).fetchall()
        for row in rows:
            approval_id = str(row["id"])
            status = str(row["status"])
            try:
                arguments = json.loads(row["arguments_json"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            try:
                result = json.loads(row["result_json"] or "{}")
            except json.JSONDecodeError:
                result = {}

            safe_arguments = sanitize_for_persistence(arguments)
            safe_result = sanitize_for_persistence(result)
            safe_arguments_json = json.dumps(safe_arguments if isinstance(safe_arguments, dict) else {"preview": safe_arguments}, ensure_ascii=False, default=str)
            safe_result_json = json.dumps(safe_result if isinstance(safe_result, dict) else {"result": safe_result}, ensure_ascii=False, default=str)
            if safe_arguments_json != (row["arguments_json"] or "{}") or safe_result_json != (row["result_json"] or "{}"):
                connection.execute(
                    "UPDATE approval_requests SET arguments_json=?,result_json=? WHERE id=?",
                    (safe_arguments_json, safe_result_json, approval_id),
                )
                scrubbed += 1

            created = _created_at(row["created_at"])
            if status in _ACTIVE and created is not None and now - created > _APPROVAL_TTL:
                connection.execute(
                    "UPDATE approval_requests SET status='denied',result_json=?,resolved_at=? WHERE id=?",
                    (json.dumps({"error": "Approval expired before execution"}), now.isoformat(), approval_id),
                )
                status = "denied"
                expired += 1

            if status in _TERMINAL:
                deletion = vault.delete(_payload_name(approval_id))
                if deletion.get("deleted"):
                    payloads_deleted += 1

    if scrubbed:
        # The rewrite above removes logical plaintext values. Checkpoint and
        # compact only when a legacy row changed, reducing the chance that old
        # SQLite/WAL pages preserve historical argument bytes.
        with db.connect() as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")

    return {"scrubbed": scrubbed, "expired": expired, "payloads_deleted": payloads_deleted}


def register(registry: Any) -> None:
    """Protect deferred tool arguments with the encrypted SecretVault.

    The approval row keeps only a bounded/redacted preview. Exact arguments are
    encrypted in the vault and removed after terminal resolution. Legacy rows
    are scrubbed and abandoned approvals expire after 24 hours. Execution is
    single-use and revalidates current authorization immediately before invoke.
    """
    db = registry.db
    vault = registry.vault
    original_resolve = db.resolve_approval

    _scrub_legacy_rows(db, vault)

    def secure_resolve(approval_id: str, status: str, result: dict[str, Any] | None = None):
        resolved = original_resolve(approval_id, status, sanitize_for_persistence(result or {}))
        if status in _TERMINAL:
            vault.delete(_payload_name(approval_id))
        return resolved

    db.resolve_approval = secure_resolve

    async def secure_execute(name: str, arguments: dict[str, Any], permissions: dict[str, Any]) -> dict[str, Any]:
        registered = registry.tools.get(name)
        if not registered:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        gate_error = registry._gate_error(registered, permissions)
        if gate_error:
            return {"ok": False, "error": gate_error}
        mode = permissions.get("approval_mode", "standard")
        if mode == "safe" and registered.risk in {"execute", "destructive", "external", "desktop"}:
            return {"ok": False, "error": f"{name} is blocked by Safe approval mode."}
        if mode == "standard" and registered.risk in {"destructive", "external", "desktop"}:
            preview = sanitize_for_persistence(arguments)
            approval = db.create_approval(
                name,
                preview if isinstance(preview, dict) else {"preview": preview},
                registered.risk,
                f"{name} has {registered.risk} side effects and requires a human decision in Standard mode.",
                permissions.get("run_id"),
            )
            try:
                stored = vault.set(_payload_name(approval["id"]), json.dumps(arguments, ensure_ascii=False, default=str))
                if not stored.get("ok"):
                    raise RuntimeError(stored.get("error") or "vault write failed")
            except Exception:
                # Never leave an executable approval whose exact payload was not
                # protected successfully.
                original_resolve(approval["id"], "denied", {"error": "encrypted approval payload storage failed"})
                raise
            return {
                "ok": False,
                "approval_required": True,
                "approval_id": approval["id"],
                "risk": registered.risk,
                "error": f"Approval required for {name}. Open the Approval Inbox.",
            }
        result = await registry._invoke(name, arguments)
        db.audit(
            "tool.executed",
            f"{name}: {'ok' if result.get('ok') else 'failed'}",
            {
                "tool": name,
                "arguments": sanitize_for_persistence(arguments),
                "ok": bool(result.get("ok")),
                "elapsed_ms": result.get("elapsed_ms", 0),
            },
            actor="agent",
        )
        return result

    async def secure_execute_approval(approval_id: str) -> dict[str, Any]:
        approval = db.get_approval(approval_id)
        if not approval:
            return {"ok": False, "error": "Approval not found"}
        if approval.get("status") != "approved":
            return {"ok": False, "error": "Approval must be approved before execution"}
        created = _created_at(approval.get("created_at"))
        if created is None or datetime.now(timezone.utc) - created > _APPROVAL_TTL:
            db.resolve_approval(approval_id, "denied", {"error": "Approval expired before execution"})
            return {"ok": False, "error": "Approval expired before execution"}

        registered = registry.tools.get(approval.get("tool_name"))
        if not registered:
            db.resolve_approval(approval_id, "denied", {"error": "Approved tool is no longer registered"})
            return {"ok": False, "error": "Approved tool is no longer registered"}
        if str(approval.get("risk")) != str(getattr(registered, "risk", "read")):
            db.resolve_approval(approval_id, "denied", {"error": "Tool risk classification changed after approval"})
            return {"ok": False, "error": "Tool risk classification changed after approval"}

        live = _live_permissions(registry)
        if live is not None:
            gate_error = registry._gate_error(registered, live)
            if gate_error:
                db.resolve_approval(approval_id, "denied", {"error": gate_error})
                return {"ok": False, "error": gate_error}
            if live.get("approval_mode") == "safe" and registered.risk in {"execute", "destructive", "external", "desktop"}:
                db.resolve_approval(approval_id, "denied", {"error": "Current Safe approval mode blocks this tool"})
                return {"ok": False, "error": "Current Safe approval mode blocks this tool"}

        # Atomically claim an approved request. This makes approvals single-use
        # even if two API requests race or a client retries after a slow response.
        with db.connect() as connection:
            claimed = connection.execute(
                "UPDATE approval_requests SET status='executing' WHERE id=? AND status='approved'",
                (approval_id,),
            ).rowcount
        if claimed != 1:
            return {"ok": False, "error": "Approval was already claimed or is no longer executable"}

        try:
            raw = vault.get_value(_payload_name(approval_id))
            arguments = json.loads(raw)
            if not isinstance(arguments, dict):
                raise ValueError("approval payload must be an object")
        except Exception as exc:
            db.resolve_approval(approval_id, "failed", {"error": "Encrypted approval payload is missing or invalid"})
            return {"ok": False, "error": f"Approval payload unavailable: {type(exc).__name__}"}
        result = await registry._invoke(approval["tool_name"], arguments)
        db.resolve_approval(approval_id, "executed" if result.get("ok") else "failed", sanitize_for_persistence(result))
        db.audit(
            "tool.approved_execution",
            f"Executed approved tool {approval['tool_name']}",
            {"approval_id": approval_id, "ok": bool(result.get("ok"))},
            actor="user",
        )
        return result

    registry.execute = secure_execute
    registry.execute_approval = secure_execute_approval
