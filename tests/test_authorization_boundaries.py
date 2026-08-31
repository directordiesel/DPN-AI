from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.approval_security import ApprovalSecurity
from app.config import Settings
from app.db import Database
from app.tools.registry import ToolRegistry
from app.vault import SecretVault
from app.workflows import WorkflowEngine


class ApprovalTool:
    risk = "external"
    gate = "connectors"


class ApprovalRegistry:
    def __init__(self, tmp_path: Path):
        self.db = Database(tmp_path / "approval.sqlite3")
        self.vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
        self.settings = SimpleNamespace(
            allow_commands_default=False,
            allow_web_default=False,
            allow_images_default=False,
            allow_browser_default=False,
            allow_desktop_default=False,
            allow_voice_default=False,
            allow_connectors_default=True,
            allow_mcp_default=False,
            allow_self_improvement_default=False,
        )
        self.tools = {"send": ApprovalTool()}
        self.invocations: list[tuple[str, dict]] = []

    def _gate_error(self, registered, permissions):
        if registered.gate == "connectors" and not permissions.get("allow_connectors", False):
            return "Connectors are disabled in DPN AI Settings."
        return None

    async def _invoke(self, name, arguments):
        self.invocations.append((name, arguments))
        return {"ok": True}

    async def execute(self, name, arguments, permissions):
        raise AssertionError("core approval security did not install")

    async def execute_approval(self, approval_id):
        raise AssertionError("core approval security did not install")


def install_core_approval_security(registry: ApprovalRegistry) -> None:
    registry.approval_security = ApprovalSecurity(registry)
    registry.execute = registry.approval_security.execute
    registry.execute_approval = registry.approval_security.execute_approval


class WorkflowAgent:
    def __init__(self):
        self.settings = {
            "allow_commands": False,
            "allow_web": False,
            "allow_images": False,
            "allow_browser": False,
            "allow_desktop": False,
            "allow_voice": False,
            "allow_connectors": False,
            "allow_mcp": False,
            "allow_self_improvement": False,
            "approval_mode": "safe",
        }

    def effective_settings(self):
        return dict(self.settings)


class WorkflowTools:
    def __init__(self):
        self.permissions: list[dict] = []

    async def execute(self, name, arguments, permissions):
        self.permissions.append(dict(permissions))
        return {"ok": True}


def test_approved_tool_revalidates_revoked_gate_before_execution(tmp_path: Path):
    registry = ApprovalRegistry(tmp_path)
    install_core_approval_security(registry)
    requested = asyncio.run(registry.execute(
        "send",
        {"token": "secret"},
        {"allow_connectors": True, "approval_mode": "standard"},
    ))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")

    registry.db.set_setting("allow_connectors", False)
    result = asyncio.run(registry.execute_approval(approval_id))

    assert result["ok"] is False
    assert "disabled" in result["error"].lower()
    assert registry.invocations == []
    assert registry.db.get_approval(approval_id)["status"] == "denied"


def test_approved_tool_is_single_use(tmp_path: Path):
    registry = ApprovalRegistry(tmp_path)
    install_core_approval_security(registry)
    requested = asyncio.run(registry.execute(
        "send",
        {"message": "once"},
        {"allow_connectors": True, "approval_mode": "standard"},
    ))
    approval_id = requested["approval_id"]
    registry.db.resolve_approval(approval_id, "approved")

    first = asyncio.run(registry.execute_approval(approval_id))
    second = asyncio.run(registry.execute_approval(approval_id))

    assert first["ok"] is True
    assert second["ok"] is False
    assert registry.invocations == [("send", {"message": "once"})]


def test_tool_registry_core_approval_security_does_not_need_plugins(tmp_path: Path):
    data_dir = tmp_path / "data"
    workspace_dir = tmp_path / "workspace"
    skills_dir = tmp_path / "skills"
    plugins_dir = tmp_path / "empty-plugins"
    voice_dir = tmp_path / "voices"
    for directory in (data_dir, workspace_dir, skills_dir, plugins_dir, voice_dir):
        directory.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        data_dir=data_dir,
        workspace_dir=workspace_dir,
        skills_dir=skills_dir,
        plugins_dir=plugins_dir,
        voice_dir=voice_dir,
        vault_key_path=data_dir / "vault.key",
    )
    db = Database(data_dir / "dpn_ai.sqlite3")
    registry = ToolRegistry(settings, db)
    assert isinstance(registry.approval_security, ApprovalSecurity)
    assert registry.plugin_errors == []

    registry.register(
        "core_external_test",
        "Core approval integration test.",
        {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]},
        lambda token: {"ok": True, "received": bool(token)},
        risk="external",
    )
    secret = "CORE-APPROVAL-PLAINTEXT-MUST-NOT-PERSIST"
    requested = asyncio.run(registry.execute(
        "core_external_test",
        {"token": secret},
        {"approval_mode": "standard"},
    ))

    assert requested["approval_required"] is True
    assert secret.encode() not in (data_dir / "dpn_ai.sqlite3").read_bytes()
    assert registry.vault.get_value(f"approval_payload.{requested['approval_id']}")


def test_workflow_ignores_stale_authorizing_permissions(tmp_path: Path):
    db = Database(tmp_path / "workflow.sqlite3")
    agent = WorkflowAgent()
    tools = WorkflowTools()
    engine = WorkflowEngine(db, agent, tools)
    workflow = db.create_workflow(
        "permission freshness",
        "",
        [{"id": "call", "type": "tool", "tool": "connector_request", "arguments": {}}],
    )

    result = asyncio.run(engine.run(
        workflow["id"],
        {},
        {"allow_connectors": True, "allow_mcp": True, "allow_self_improvement": True, "approval_mode": "standard"},
    ))

    assert result["ok"] is True
    assert len(tools.permissions) == 1
    used = tools.permissions[0]
    assert used["allow_connectors"] is False
    assert used["allow_mcp"] is False
    assert used["allow_self_improvement"] is False
    assert used["approval_mode"] == "safe"
