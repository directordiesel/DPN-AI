from __future__ import annotations

import json
import re
from typing import Any

from app.db import Database


_TOKEN = re.compile(r"\{\{([A-Za-z0-9_.-]+)\}\}")


class WorkflowEngine:
    """Deterministic reusable workflows combining tools and agent prompts."""

    def __init__(self, db: Database, agent: Any, tools: Any):
        self.db = db
        self.agent = agent
        self.tools = tools

    @staticmethod
    def _resolve(value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            def repl(match: re.Match[str]) -> str:
                current: Any = context
                for part in match.group(1).split("."):
                    if not isinstance(current, dict):
                        return ""
                    current = current.get(part, "")
                return str(current)
            return _TOKEN.sub(repl, value)
        if isinstance(value, list):
            return [WorkflowEngine._resolve(item, context) for item in value]
        if isinstance(value, dict):
            return {key: WorkflowEngine._resolve(item, context) for key, item in value.items()}
        return value

    def _current_permissions(self, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build permissions from live settings immediately before a tool call.

        Persisted workflow/job payloads must never become authorization tokens.
        Production agents expose effective_settings(), and all authorization gates
        are refreshed for every tool invocation. Minimal test/fake agents that do
        not expose runtime settings keep the legacy supplied/default permission
        shape so isolated workflow tests remain usable.
        """
        effective_settings = getattr(self.agent, "effective_settings", None)
        if not callable(effective_settings):
            return dict(supplied or {"approval_mode": "standard"})

        effective = effective_settings()
        permissions = {
            "allow_commands": bool(effective.get("allow_commands", False)),
            "allow_web": bool(effective.get("allow_web", False)),
            "allow_images": bool(effective.get("allow_images", False)),
            "allow_browser": bool(effective.get("allow_browser", False)),
            "allow_desktop": bool(effective.get("allow_desktop", False)),
            "allow_voice": bool(effective.get("allow_voice", False)),
            "allow_connectors": bool(effective.get("allow_connectors", False)),
            "allow_mcp": bool(effective.get("allow_mcp", False)),
            "allow_self_improvement": bool(effective.get("allow_self_improvement", False)),
            "approval_mode": str(effective.get("approval_mode") or "standard"),
        }
        if supplied and supplied.get("run_id"):
            permissions["run_id"] = supplied["run_id"]
        return permissions

    async def run(self, workflow_id: str, inputs: dict[str, Any] | None = None,
                  permissions: dict[str, Any] | None = None) -> dict[str, Any]:
        workflow = self.db.get_workflow(workflow_id)
        if not workflow or not workflow.get("enabled"):
            return {"ok": False, "error": "Workflow not found or disabled"}
        inputs = inputs or {}
        run_id = self.db.create_workflow_run(workflow_id, inputs)
        context: dict[str, Any] = {"inputs": inputs, "steps": {}}
        try:
            for index, raw_step in enumerate(workflow.get("steps", [])[:100]):
                step = self._resolve(raw_step, context)
                step_id = str(step.get("id") or f"step_{index + 1}")
                kind = step.get("type")
                if kind == "tool":
                    result = await self.tools.execute(
                        str(step.get("tool", "")),
                        step.get("arguments", {}) if isinstance(step.get("arguments"), dict) else {},
                        self._current_permissions(permissions),
                    )
                elif kind == "prompt":
                    response = await self.agent.run(
                        conversation_id=None,
                        user_message=str(step.get("prompt", "")),
                        profile=str(step.get("profile", "auto")),
                        project_id=step.get("project_id"),
                        source="workflow",
                    )
                    result = {"ok": True, "message": response.message, "conversation_id": response.conversation_id,
                              "run_id": response.run_id, "generated_files": response.generated_files}
                elif kind == "set":
                    result = {"ok": True, "value": step.get("value")}
                elif kind == "condition":
                    source = str(step.get("source", ""))
                    equals = step.get("equals")
                    result = {"ok": True, "matched": source == str(equals)}
                    if not result["matched"] and step.get("stop_on_false", False):
                        context["steps"][step_id] = result
                        break
                else:
                    result = {"ok": False, "error": f"Unsupported workflow step type: {kind}"}
                context["steps"][step_id] = result
                if not result.get("ok") and step.get("continue_on_error") is not True:
                    raise RuntimeError(f"Workflow step {step_id} failed: {result.get('error', 'unknown error')}")
            self.db.finish_workflow_run(run_id, "completed", context)
            return {"ok": True, "workflow_run_id": run_id, "outputs": context}
        except Exception as exc:  # noqa: BLE001
            self.db.finish_workflow_run(run_id, "failed", context, f"{type(exc).__name__}: {exc}")
            return {"ok": False, "workflow_run_id": run_id, "outputs": context, "error": str(exc)}
