from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser_adapter import BrowserAdapter
from app.connectors import ConnectorHub
from app.db import Database
from app.orchestrator import MissionOrchestrator
from app.semantic import SemanticMemory
from app.skills import SkillManager
from app.vault import SecretVault
from app.workflows import WorkflowEngine


def test_v3_database_mission_graph(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    mission = db.create_mission("Build a system")
    first = db.add_mission_step(mission["id"], 0, "director", "Inspect", "Inspect state")
    second = db.add_mission_step(mission["id"], 1, "software", "Build", "Build it", [first["id"]])
    db.update_mission_step(first["id"], "completed", {"ok": True}, increment_attempts=True)
    loaded = db.get_mission(mission["id"])
    assert loaded is not None
    assert len(loaded["steps"]) == 2
    assert loaded["steps"][0]["attempts"] == 1
    assert loaded["steps"][1]["dependencies"] == [first["id"]]


def test_approval_lifecycle(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    approval = db.create_approval("desktop_automation", {"actions": []}, "desktop", "Needs consent")
    assert db.list_approvals()[0]["status"] == "pending"
    db.resolve_approval(approval["id"], "approved")
    assert db.get_approval(approval["id"])["status"] == "approved"


def test_skill_manager_round_trip(tmp_path: Path):
    manager = SkillManager(tmp_path / "skills")
    result = manager.create("code-review", "Code Review", "Review code", "Inspect, test, report.")
    assert result["ok"]
    assert manager.get("code-review")["skill"]["name"] == "Code Review"
    assert "Inspect, test" in manager.context(["code-review"])


def test_vault_encrypts_values(tmp_path: Path):
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    vault.set("API_TOKEN", "super-secret-value")
    raw = (tmp_path / "vault.json").read_text()
    assert "super-secret-value" not in raw
    assert vault.get_value("API_TOKEN") == "super-secret-value"
    assert vault.resolve({"Authorization": "Bearer {{secret:API_TOKEN}}"})["Authorization"] == "Bearer super-secret-value"


def test_connector_prevents_host_escape(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    hub = ConnectorHub(db, vault, allow_private_network=True)
    connector = hub.create("Test", "https://example.com/api", allowed_methods=["GET"])["connector"]
    assert connector["config"]["allowed_methods"] == ["GET"]


@pytest.mark.asyncio
async def test_semantic_memory_with_mock_embeddings(tmp_path: Path):
    class FakeOllama:
        async def embed(self, model, inputs):
            return [[1.0, 0.0] if "alpha" in text else [0.0, 1.0] for text in inputs]

    db = Database(tmp_path / "data.sqlite3")
    memory = SemanticMemory(db, FakeOllama(), "mock")
    await memory.add("alpha project", namespace="test")
    await memory.add("beta project", namespace="test")
    result = await memory.search("alpha question", namespace="test")
    assert result["results"][0]["content"] == "alpha project"
    assert result["results"][0]["score"] == 1.0


def test_browser_adapter_reports_optional_status(tmp_path: Path):
    status = BrowserAdapter(tmp_path).status()
    assert status["ok"] is True
    assert "available" in status


@pytest.mark.asyncio
async def test_workflow_engine_tool_steps(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    workflow = db.create_workflow("Test", "", [
        {"id": "one", "type": "set", "value": "hello"},
        {"id": "two", "type": "tool", "tool": "echo", "arguments": {"value": "{{steps.one.value}}"}},
    ])

    class Tools:
        async def execute(self, name, args, permissions):
            return {"ok": True, "echo": args["value"]}

    engine = WorkflowEngine(db, SimpleNamespace(), Tools())
    result = await engine.run(workflow["id"])
    assert result["ok"]
    assert result["outputs"]["steps"]["two"]["echo"] == "hello"


@pytest.mark.asyncio
async def test_mission_orchestrator_fallback_executes_steps(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")

    class FailingPlanner:
        async def chat(self, **kwargs):
            raise RuntimeError("offline")

    class FakeAgent:
        settings = SimpleNamespace(default_model="mock")
        def effective_settings(self):
            return {"model": "mock", "worker_model": "mock", "planner_model": "mock", "reviewer_model": "mock", "think_level": False}
        async def run(self, **kwargs):
            return SimpleNamespace(message="done", run_id="run", profile=kwargs["profile"], generated_files=[], traces=[])

    settings = SimpleNamespace(max_mission_steps=12)
    orchestrator = MissionOrchestrator(settings, db, FailingPlanner(), FakeAgent())
    result = await orchestrator.run("Build a code app")
    assert result["status"] == "completed"
    assert len(db.get_mission(result["mission_id"])["steps"]) == 3


def test_semantic_table_survives_reopen(tmp_path: Path):
    path = tmp_path / "data.sqlite3"
    db = Database(path)
    db.upsert_semantic_item("id", "global", "test", "content", [1.0], {"a": 1})
    db2 = Database(path)
    assert db2.get_semantic_item("id")["metadata"] == {"a": 1}