from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.tools.registry import ToolRegistry


def make_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", workspace_dir=tmp_path / "workspace", skills_dir=tmp_path / "skills", vault_key_path=tmp_path / "data" / "vault.key")


@pytest.mark.asyncio
async def test_standard_mode_queues_external_approval(tmp_path: Path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    registry = ToolRegistry(settings, db)
    registry.register("external_test", "test", {"type": "object", "properties": {}}, lambda: {"ok": True}, risk="external")
    result = await registry.execute("external_test", {}, {"approval_mode": "standard"})
    assert result["approval_required"] is True
    assert len(db.list_approvals()) == 1


@pytest.mark.asyncio
async def test_autonomous_mode_executes_external_tool(tmp_path: Path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    registry = ToolRegistry(settings, db)
    registry.register("external_test", "test", {"type": "object", "properties": {}}, lambda: {"ok": True, "value": 7}, risk="external")
    result = await registry.execute("external_test", {}, {"approval_mode": "autonomous"})
    assert result["ok"] and result["value"] == 7


@pytest.mark.asyncio
async def test_gate_blocks_disabled_desktop(tmp_path: Path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    registry = ToolRegistry(settings, db)
    result = await registry.execute("desktop_automation", {"actions": []}, {"approval_mode": "autonomous", "allow_desktop": False})
    assert not result["ok"]
    assert "disabled" in result["error"].lower()