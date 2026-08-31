from __future__ import annotations

import os
from pathlib import Path

from app.db import Database
from app.mcp_bridge import MCPBridge
from app.vault import SecretVault


def _bridge(tmp_path: Path, allow_external: bool = False) -> MCPBridge:
    db = Database(tmp_path / "data.sqlite3")
    vault = SecretVault(tmp_path / "vault.key", tmp_path / "vault.json")
    return MCPBridge(db, vault, allow_external=allow_external)


def test_stdio_mcp_rejects_executable_paths(tmp_path: Path):
    bridge = _bridge(tmp_path)
    result = bridge.create_server("Unsafe", "stdio", command="./python", args=["server.py"])
    assert result["ok"] is False
    assert "bare" in result["error"].lower()


def test_stdio_mcp_rejects_unapproved_shells_and_package_runners(tmp_path: Path):
    bridge = _bridge(tmp_path)
    assert bridge.create_server("Shell", "stdio", command="bash")["ok"] is False
    assert bridge.create_server("Package runner", "stdio", command="npx")["ok"] is False


def test_stdio_mcp_rejects_inline_runtime_execution(tmp_path: Path):
    bridge = _bridge(tmp_path)
    python_result = bridge.create_server("Inline Python", "stdio", command="python", args=["-c", "print(1)"])
    node_result = bridge.create_server("Inline Node", "stdio", command="node", args=["--eval", "console.log(1)"])
    assert python_result["ok"] is False
    assert node_result["ok"] is False


def test_stdio_mcp_rejects_invalid_environment_names(tmp_path: Path):
    bridge = _bridge(tmp_path)
    result = bridge.create_server("Bad env", "stdio", command="python", env={"BAD-NAME": "value"})
    assert result["ok"] is False
    assert "environment variable name" in result["error"].lower()


def test_stdio_mcp_minimal_environment_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("DPN_AI_API_TOKEN", "should-not-leak")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    env = MCPBridge._minimal_stdio_env({"SAFE_VALUE": "ok"})
    assert env["SAFE_VALUE"] == "ok"
    assert "DPN_AI_API_TOKEN" not in env


def test_http_mcp_rejects_embedded_credentials_query_and_fragment(tmp_path: Path):
    bridge = _bridge(tmp_path, allow_external=True)
    credentials = bridge.create_server("Creds", "http", url="https://user:pass@example.com/mcp")
    query = bridge.create_server("Query", "http", url="https://example.com/mcp?token=abc")
    fragment = bridge.create_server("Fragment", "http", url="https://example.com/mcp#section")
    assert credentials["ok"] is False
    assert query["ok"] is False
    assert fragment["ok"] is False


def test_host_scope_rejects_reserved_multicast_and_unspecified_addresses():
    assert MCPBridge._host_scope("0.0.0.0") == "unsafe"
    assert MCPBridge._host_scope("224.0.0.1") == "unsafe"
    assert MCPBridge._host_scope("240.0.0.1") == "unsafe"
