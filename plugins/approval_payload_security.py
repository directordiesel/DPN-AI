from __future__ import annotations

import json
from typing import Any

from app.persistence_security import sanitize_for_persistence


_PREFIX = "approval_payload."
_TERMINAL = {"denied", "executed", "failed"}


def register(registry: Any) -> None:
    """Protect deferred tool arguments with the encrypted SecretVault.

    The approval row keeps only a bounded/redacted preview. Exact arguments are
    encrypted in the vault and removed after terminal resolution.
    """
    db = registry.db
    vault = registry.vault
    original_resolve = db.resolve_approval

    def payload_name(approval_id: str) -> str:
        return f"{_PREFIX}{approval_id}"

    def secure_resolve(approval_id: str, status: str, result: dict[str, Any] | None = None):
        resolved = original_resolve(approval_id, status, sanitize_for_persistence(result or {}))
        if status in _TERMINAL:
            vault.delete(payload_name(approval_id))
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
                stored = vault.set(payload_name(approval["id"]), json.dumps(arguments, ensure_ascii=False, default=str))
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
        try:
            raw = vault.get_value(payload_name(approval_id))
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
