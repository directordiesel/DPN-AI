from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.capability_forge import CapabilityForge
from app.cognitive_kernel import CognitiveKernel
from app.config import Settings
from app.db import Database
from app.job_supervisor import JobSupervisor
from app.knowledge_graph import KnowledgeGraph
from app.mcp_bridge import MCPBridge
from app.plugins import load_plugins
from app.sandbox import SandboxManager
from app.tools.registry import ToolRegistry
from app.vault import SecretVault


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        skills_dir=tmp_path / "skills",
        plugins_dir=tmp_path / "plugins",
        vault_key_path=tmp_path / "data" / "vault.key",
    )


def test_goal_contract_classifies_and_requires_evidence(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    kernel = CognitiveKernel(db, workspace)
    contract = kernel.derive_contract(
        "Build and test a standalone FiveM QBCore application, package a .zip, and verify the release"
    )
    assert "software" in contract.task_classes
    assert "fivem" in contract.task_classes
    assert "release archive" in contract.deliverables
    assert "validation evidence" in contract.deliverables
    assert any("tests" in item.lower() for item in contract.success_criteria)


def test_plan_normalization_adds_retries_evidence_and_rollback(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    kernel = CognitiveKernel(db, workspace)
    contract = kernel.derive_contract("Create a tested software release")
    plan = kernel.normalize_plan(
        {"steps": [{"title": "Build", "role": "software", "instructions": "Implement it"}]},
        contract,
        10,
    )
    step = plan["steps"][0]
    assert step["max_attempts"] >= 1
    assert step["evidence_required"]
    assert "Restore" in step["rollback"]


def test_deterministic_evidence_verifier_detects_missing_artifact(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    kernel = CognitiveKernel(db, workspace)
    contract = kernel.derive_contract("Create and verify a software application")
    result = kernel.verify_evidence(
        [{"generated_files": ["missing.zip"], "tool_count": 3}],
        contract,
    )
    assert result["verdict"] != "pass"
    assert any("missing" in issue.lower() for issue in result["issues"])


def test_knowledge_graph_fact_search_and_neighborhood(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    graph = KnowledgeGraph(db)
    result = graph.remember_fact("DPN AI", "uses", "Ollama", source="test", confidence=0.9)
    assert result["ok"]
    found = graph.search("dpn ai")
    assert found["nodes"][0]["label"] == "DPN AI"
    neighborhood = graph.neighborhood(result["subject"]["id"])
    assert neighborhood["ok"]
    assert len(neighborhood["graph"]["edges"]) == 1
    assert graph.stats()["edges"] == 1


def test_background_job_recovery_and_retry_data(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    job = db.create_background_job("direct", {"message": "inspect workspace"})
    db.update_background_job(job["id"], "running", {"stage": "started"})
    assert db.requeue_interrupted_jobs() == 1
    recovered = db.get_background_job(job["id"])
    assert recovered["status"] == "queued"
    assert "Recovered" in recovered["error_text"]


@pytest.mark.asyncio
async def test_background_supervisor_executes_direct_job(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")

    class Agent:
        async def run(self, **kwargs):
            return SimpleNamespace(model_dump=lambda: {"ok": True, "message": kwargs["user_message"], "generated_files": []})

    supervisor = JobSupervisor(db, Agent(), SimpleNamespace(), SimpleNamespace(), max_concurrency=1)
    await supervisor.start()
    try:
        submitted = await supervisor.submit("direct", {"message": "hello"})
        await supervisor.queue.join()
        loaded = db.get_background_job(submitted["job"]["id"])
        assert loaded["status"] == "completed"
        assert loaded["result"]["message"] == "hello"
    finally:
        await supervisor.stop()


def test_capability_forge_validates_and_promotes_safe_plugin(tmp_path: Path):
    forge = CapabilityForge(tmp_path / "plugins", tmp_path / "data")
    code = "def register(registry):\n    registry.register('hello_v5', 'hello', {'type':'object','properties':{}}, lambda: {'ok': True})\n"
    assert forge.stage("hello-v5", code)["ok"]
    validation = forge.validate("hello-v5")
    assert validation["valid"] is True
    promoted = forge.promote("hello-v5")
    assert promoted["ok"]
    assert (tmp_path / "plugins" / "hello_v5.py").is_file()


def test_capability_forge_rejects_dynamic_execution(tmp_path: Path):
    forge = CapabilityForge(tmp_path / "plugins", tmp_path / "data")
    code = "def register(registry):\n    eval('1+1')\n"
    forge.stage("unsafe", code)
    validation = forge.validate("unsafe")
    assert validation["valid"] is False
    assert any("Dynamic execution" in item["message"] for item in validation["issues"])


def test_capability_forge_rejects_symlink_plugin_target(tmp_path: Path):
    forge = CapabilityForge(tmp_path / "plugins", tmp_path / "data")
    code = "def register(registry):\n    return None\n"
    assert forge.stage("linked", code)["ok"]
    outside = tmp_path / "outside.py"
    outside.write_text("do not replace", encoding="utf-8")
    target = tmp_path / "plugins" / "linked.py"
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    promoted = forge.promote("linked")
    assert promoted["ok"] is False
    assert "symlink" in promoted["error"].lower()
    assert outside.read_text(encoding="utf-8") == "do not replace"


def test_plugin_loader_rejects_symlinked_plugin(tmp_path: Path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    outside = tmp_path / "outside_plugin.py"
    outside.write_text("def register(registry):\n    registry.registered = True\n", encoding="utf-8")
    linked = plugin_dir / "linked.py"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    registry = SimpleNamespace(registered=False)
    errors = load_plugins(plugin_dir, registry)
    assert registry.registered is False
    assert errors and "symlink" in errors[0]["error"].lower()


def test_mcp_server_deny_by_default_and_allowlist_update(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    bridge = MCPBridge(db, vault, allow_external=False)
    created = bridge.create_server("Local tools", "stdio", command="python", args=["server.py"])
    assert created["ok"]
    server_id = created["server"]["id"]
    assert created["server"]["allowed_tools"] == []
    db.cache_mcp_tools(server_id, [{"name": "read_project"}, {"name": "write_project"}])
    updated = bridge.update_server(server_id, allowed_tools=["read_project"])
    assert updated["ok"]
    assert updated["server"]["allowed_tools"] == ["read_project"]
    rejected = bridge.update_server(server_id, allowed_tools=["not_discovered"])
    assert rejected["ok"] is False


def test_mcp_sensitive_env_requires_encrypted_secret_reference(tmp_path: Path):
    db = Database(tmp_path / "data.sqlite3")
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    bridge = MCPBridge(db, vault)
    rejected = bridge.create_server("Unsafe", "stdio", command="python", env={"API_TOKEN": "plaintext"})
    assert rejected["ok"] is False
    vault.set("MCP_TOKEN", "private")
    accepted = bridge.create_server("Safe", "stdio", command="python", env={"API_TOKEN": "{{secret:MCP_TOKEN}}"})
    assert accepted["ok"]
    assert accepted["server"]["config"]["env"]["API_TOKEN"] == "[configured]"


def test_tool_context_is_focused_but_discoverable(tmp_path: Path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_path)
    registry = ToolRegistry(settings, db)
    selected = registry.select_names("analyze a CSV and create a chart", profile="data")
    assert "run_python_sandbox" in selected
    assert "discover_tools" in selected
    assert len(selected) < len(registry.tools)
    discovered = registry.discover("voice")
    assert any("voice" in item["name"] or "voice" in item["description"].lower() for item in discovered["tools"])


def test_sandbox_reports_security_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sandbox = SandboxManager(tmp_path / "workspace", allow_host_fallback=False)
    monkeypatch.setattr(sandbox, "_docker_available", lambda: False)
    result = sandbox.run_python("print('hello')")
    assert result["ok"] is False
    assert "host fallback is disabled" in result["error"].lower()
    assert "not a security isolation boundary" in sandbox.status()["warning"]


def test_capability_forge_preserves_and_restores_backup(tmp_path: Path):
    forge = CapabilityForge(tmp_path / "plugins", tmp_path / "data")
    first = "def register(registry):\n    registry.register('versioned', 'v1', {'type':'object','properties':{}}, lambda: {'version': 1})\n"
    second = "def register(registry):\n    registry.register('versioned', 'v2', {'type':'object','properties':{}}, lambda: {'version': 2})\n"
    forge.stage("versioned", first)
    forge.promote("versioned")
    forge.stage("versioned", second, overwrite=True)
    forge.promote("versioned")
    listing = forge.list()
    assert listing["backups"]
    restored = forge.rollback("versioned")
    assert restored["ok"]
    assert "version': 1" in (tmp_path / "plugins" / "versioned.py").read_text()


def test_sandbox_rejects_network_even_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sandbox = SandboxManager(tmp_path / "workspace", allow_host_fallback=True)
    monkeypatch.setattr(sandbox, "_docker_available", lambda: False)
    result = sandbox.run_python("print('hello')", network=True, use_host_fallback=True)
    assert result["ok"] is False
    assert "network access is disabled" in result["error"].lower()
