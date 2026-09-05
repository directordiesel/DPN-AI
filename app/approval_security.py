from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.persistence_security import sanitize_for_persistence
from app.tool_permission_runtime import ToolPermissionRuntime


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


class ApprovalSecurity:
    """Core approval execution boundary for DPN AI.

    Exact deferred tool arguments are stored only in SecretVault. SQLite keeps a
    bounded/redacted preview. Approval execution is single-use, expires after 24
    hours, revalidates current authorization immediately before invoke, and never
    replays an ambiguous interrupted execution.
    """

    def __init__(self, registry: Any):
        self.registry = registry
        self.db = registry.db
        self.vault = registry.vault
        self.permission_runtime = getattr(registry, "permission_runtime", ToolPermissionRuntime())
        self._original_resolve = self.db.resolve_approval
        self._scrub_legacy_rows()
        # Keep direct database approval decisions safe. The API and other callers
        # already resolve approvals through db.resolve_approval; wrapping it here
        # guarantees terminal decisions also destroy encrypted payloads.
        self.db.resolve_approval = self.resolve_approval

    def _live_permissions(self) -> dict[str, Any] | None:
        settings = getattr(self.registry, "settings", None)
        if settings is None or not hasattr(self.db, "all_settings"):
            return None
        stored = self.db.all_settings()
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
            "use_v9_permissions": bool(stored.get("use_v9_permissions", False)),
        }

    def _scrub_legacy_rows(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        scrubbed = 0
        expired = 0
        interrupted = 0
        payloads_deleted = 0

        with self.db.connect() as connection:
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
                safe_arguments_json = json.dumps(
                    safe_arguments if isinstance(safe_arguments, dict) else {"preview": safe_arguments},
                    ensure_ascii=False,
                    default=str,
                )
                safe_result_json = json.dumps(
                    safe_result if isinstance(safe_result, dict) else {"result": safe_result},
                    ensure_ascii=False,
                    default=str,
                )
                if safe_arguments_json != (row["arguments_json"] or "{}") or safe_result_json != (row["result_json"] or "{}"):
                    connection.execute(
                        "UPDATE approval_requests SET arguments_json=?,result_json=? WHERE id=?",
                        (safe_arguments_json, safe_result_json, approval_id),
                    )
                    scrubbed += 1

                if status == "executing":
                    connection.execute(
                        "UPDATE approval_requests SET status='failed',result_json=?,resolved_at=? WHERE id=?",
                        (
                            json.dumps({"error": "Approval execution was interrupted; replay blocked"}),
                            now.isoformat(),
                            approval_id,
                        ),
                    )
                    status = "failed"
                    interrupted += 1

                created = _created_at(row["created_at"])
                if status in _ACTIVE and (created is None or now - created > _APPROVAL_TTL):
                    connection.execute(
                        "UPDATE approval_requests SET status='denied',result_json=?,resolved_at=? WHERE id=?",
                        (json.dumps({"error": "Approval expired before execution"}), now.isoformat(), approval_id),
                    )
                    status = "denied"
                    expired += 1

                if status in _TERMINAL:
                    deletion = self.vault.delete(_payload_name(approval_id))
                    if deletion.get("deleted"):
                        payloads_deleted += 1

        if scrubbed:
            with self.db.connect() as connection:
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")

        return {
            "scrubbed": scrubbed,
            "expired": expired,
            "interrupted": interrupted,
            "payloads_deleted": payloads_deleted,
        }

    def resolve_approval(self, approval_id: str, status: str, result: dict[str, Any] | None = None):
        resolved = self._original_resolve(approval_id, status, sanitize_for_persistence(result or {}))
        if status in _TERMINAL:
            self.vault.delete(_payload_name(approval_id))
        return resolved

    async def execute(self, name: str, arguments: dict[str, Any], permissions: dict[str, Any]) -> dict[str, Any]:
        registered = self.registry.tools.get(name)
        if not registered:
            return {"ok": False, "error": f"Unknown tool: {name}"}

        authorization = self.permission_runtime.authorize(
            tool_name=name,
            declared_risk=registered.risk,
            gate=registered.gate,
            permissions=permissions,
            use_v9_policy=bool(permissions.get("use_v9_permissions", False)),
        )
        if not authorization.allowed and not authorization.approval_required:
            return {"ok": False, "error": authorization.reason, "risk": authorization.profile.risk.value}

        if authorization.approval_required:
            preview = sanitize_for_persistence(arguments)
            effective_risk = authorization.profile.risk.value
            approval = self.db.create_approval(
                name,
                preview if isinstance(preview, dict) else {"preview": preview},
                effective_risk,
                authorization.reason,
                permissions.get("run_id"),
            )
            try:
                stored = self.vault.set(
                    _payload_name(approval["id"]),
                    json.dumps(arguments, ensure_ascii=False, default=str),
                )
                if not stored.get("ok"):
                    raise RuntimeError(stored.get("error") or "vault write failed")
            except Exception:
                self._original_resolve(
                    approval["id"],
                    "denied",
                    {"error": "encrypted approval payload storage failed"},
                )
                self.vault.delete(_payload_name(approval["id"]))
                raise
            return {
                "ok": False,
                "approval_required": True,
                "approval_id": approval["id"],
                "risk": effective_risk,
                "permission_source": authorization.decision.source,
                "error": f"Approval required for {name}. Open the Approval Inbox.",
            }

        result = await self.registry._invoke(name, arguments)
        if not isinstance(result, dict):
            result = {"ok": False, "error": "Tool returned an invalid result type"}
        self.db.audit(
            "tool.executed",
            f"{name}: {'ok' if result.get('ok') else 'failed'}",
            {
                "tool": name,
                "arguments": sanitize_for_persistence(arguments),
                "risk": authorization.profile.risk.value,
                "permission_source": authorization.decision.source,
                "ok": bool(result.get("ok")),
                "elapsed_ms": result.get("elapsed_ms", 0),
            },
            actor="agent",
        )
        return result

    async def execute_approval(self, approval_id: str) -> dict[str, Any]:
        approval = self.db.get_approval(approval_id)
        if not approval:
            return {"ok": False, "error": "Approval not found"}
        if approval.get("status") != "approved":
            return {"ok": False, "error": "Approval must be approved before execution"}

        created = _created_at(approval.get("created_at"))
        if created is None or datetime.now(timezone.utc) - created > _APPROVAL_TTL:
            self.db.resolve_approval(approval_id, "denied", {"error": "Approval expired before execution"})
            return {"ok": False, "error": "Approval expired before execution"}

        tool_name = str(approval.get("tool_name") or "")
        registered = self.registry.tools.get(tool_name)
        if not registered:
            self.db.resolve_approval(approval_id, "denied", {"error": "Approved tool is no longer registered"})
            return {"ok": False, "error": "Approved tool is no longer registered"}

        live = self._live_permissions()
        if live is not None:
            authorization = self.permission_runtime.authorize(
                tool_name=tool_name,
                declared_risk=registered.risk,
                gate=registered.gate,
                permissions=live,
                use_v9_policy=bool(live.get("use_v9_permissions", False)),
            )
            current_risk = authorization.profile.risk.value
            if str(approval.get("risk")) != current_risk:
                self.db.resolve_approval(approval_id, "denied", {"error": "Tool risk classification changed after approval"})
                return {"ok": False, "error": "Tool risk classification changed after approval"}
            # A previously approved one-time action may still report approval_required
            # during revalidation. Only hard denial blocks execution here.
            if not authorization.allowed and not authorization.approval_required:
                self.db.resolve_approval(approval_id, "denied", {"error": authorization.reason})
                return {"ok": False, "error": authorization.reason}
        else:
            # Without live settings, still reject a classifier change.
            current = self.permission_runtime.authorize(
                tool_name=tool_name,
                declared_risk=registered.risk,
                gate=None,
                permissions={},
                use_v9_policy=False,
            )
            if str(approval.get("risk")) != current.profile.risk.value:
                self.db.resolve_approval(approval_id, "denied", {"error": "Tool risk classification changed after approval"})
                return {"ok": False, "error": "Tool risk classification changed after approval"}

        with self.db.connect() as connection:
            claimed = connection.execute(
                "UPDATE approval_requests SET status='executing' WHERE id=? AND status='approved'",
                (approval_id,),
            ).rowcount
        if claimed != 1:
            return {"ok": False, "error": "Approval was already claimed or is no longer executable"}

        try:
            raw = self.vault.get_value(_payload_name(approval_id))
            arguments = json.loads(raw)
            if not isinstance(arguments, dict):
                raise ValueError("approval payload must be an object")
        except Exception as exc:
            self.db.resolve_approval(approval_id, "failed", {"error": "Encrypted approval payload is missing or invalid"})
            return {"ok": False, "error": f"Approval payload unavailable: {type(exc).__name__}"}

        try:
            result = await self.registry._invoke(tool_name, arguments)
            if not isinstance(result, dict):
                result = {"ok": False, "error": "Tool returned an invalid result type"}
            self.db.resolve_approval(
                approval_id,
                "executed" if result.get("ok") else "failed",
                sanitize_for_persistence(result),
            )
            self.db.audit(
                "tool.approved_execution",
                f"Executed approved tool {tool_name}",
                {"approval_id": approval_id, "ok": bool(result.get("ok"))},
                actor="user",
            )
            return result
        except asyncio.CancelledError:
            self.db.resolve_approval(
                approval_id,
                "failed",
                {"error": "Approved tool execution was cancelled; replay blocked"},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            safe_error = sanitize_for_persistence(f"{type(exc).__name__}: {exc}")
            self.db.resolve_approval(approval_id, "failed", {"error": safe_error})
            self.db.audit(
                "tool.approved_execution_failed",
                f"Approved tool {tool_name} raised an exception",
                {"approval_id": approval_id, "error": safe_error},
                actor="user",
            )
            return {"ok": False, "error": "Approved tool execution failed"}
        finally:
            self.vault.delete(_payload_name(approval_id))
