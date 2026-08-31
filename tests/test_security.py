from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from app.connectors import ConnectorHub
from app.tools.filesystem import WorkspaceFS
from app.tools.shell import SafeCommandRunner
from app.tools.web_tools import _safe_public_url
from app.vault import SecretVault


def test_workspace_blocks_path_traversal(tmp_path: Path) -> None:
    fs = WorkspaceFS(tmp_path / "workspace")
    with pytest.raises(ValueError):
        fs.resolve("../../outside.txt")


def test_workspace_write_read_and_patch(tmp_path: Path) -> None:
    fs = WorkspaceFS(tmp_path / "workspace")
    result = fs.write_file("project/main.py", "print('old')\n")
    assert result["ok"] is True
    patched = fs.replace_text("project/main.py", "old", "DPN AI")
    assert patched["ok"] is True
    read = fs.read_file("project/main.py")
    assert "DPN AI" in read["content"]


def test_shell_blocks_system_commands(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path / "workspace")
    result = runner.run("rm -rf .")
    assert result["ok"] is False
    assert "not allowed" in result["error"] or "blocked" in result["error"]


def test_shell_blocks_inline_python(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path / "workspace")
    result = runner.run('python -c "print(1)"')
    assert result["ok"] is False
    assert "Inline Python" in result["error"]


def test_shell_rejects_executable_paths(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path / "workspace")
    result = runner.run("./python script.py")
    assert result["ok"] is False
    assert "bare name" in result["error"]


def test_shell_blocks_remote_package_install(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path / "workspace")
    with mock.patch("app.tools.shell.shutil.which", return_value="/usr/bin/pip"):
        result = runner.run("pip install requests")
    assert result["ok"] is False
    assert "package operation" in result["error"]


def test_shell_blocks_npx_remote_execution(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path / "workspace")
    result = runner.run("npx some-package")
    assert result["ok"] is False
    assert "not allowed" in result["error"]


def test_shell_blocks_git_runtime_command_override(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path / "workspace")
    with mock.patch("app.tools.shell.shutil.which", return_value="/usr/bin/git"):
        result = runner.run('git -c core.sshCommand="ssh -o ProxyCommand=helper" status')
    assert result["ok"] is False
    assert "configuration overrides" in result["error"]


def test_shell_does_not_inherit_sensitive_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    runner = SafeCommandRunner(workspace)
    monkeypatch.setenv("DPN_TEST_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("DPN_TEST_VISIBLE", "safe-value")
    completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
    with (
        mock.patch("app.tools.shell.shutil.which", return_value="/usr/bin/python"),
        mock.patch("app.tools.shell.subprocess.run", return_value=completed) as run_mock,
    ):
        result = runner.run("python script.py")
    assert result["ok"] is True
    child_env = run_mock.call_args.kwargs["env"]
    assert "DPN_TEST_API_KEY" not in child_env
    assert child_env["DPN_TEST_VISIBLE"] == "safe-value"
    assert child_env["DPN_AI_WORKSPACE"] == str(workspace.resolve())


def test_shell_rejects_workspace_shadow_executable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    fake_python = workspace / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("placeholder", encoding="utf-8")
    runner = SafeCommandRunner(workspace)
    with mock.patch("app.tools.shell.shutil.which", return_value=str(fake_python)):
        result = runner.run("python script.py")
    assert result["ok"] is False
    assert "inside the DPN AI workspace" in result["error"]


def test_vault_round_trip(tmp_path: Path) -> None:
    vault = SecretVault(tmp_path / "security" / "vault.key", tmp_path / "data" / "vault.json")
    assert vault.set("api.token", "super-secret-value")["ok"] is True
    assert vault.get_value("api.token") == "super-secret-value"
    assert vault.list() == {"ok": True, "secrets": ["api.token"]}
    raw = (tmp_path / "data" / "vault.json").read_text(encoding="utf-8")
    assert "super-secret-value" not in raw


def test_vault_refuses_to_overwrite_corrupt_data(tmp_path: Path) -> None:
    key_path = tmp_path / "security" / "vault.key"
    data_path = tmp_path / "data" / "vault.json"
    vault = SecretVault(key_path, data_path)
    vault.set("existing", "keep-me")
    data_path.write_text("{corrupt-json", encoding="utf-8")
    before = data_path.read_bytes()

    with pytest.raises(ValueError, match="corrupted"):
        vault.set("new-secret", "must-not-replace-vault")

    assert data_path.read_bytes() == before


def test_vault_rejects_invalid_structure(tmp_path: Path) -> None:
    key_path = tmp_path / "security" / "vault.key"
    data_path = tmp_path / "data" / "vault.json"
    vault = SecretVault(key_path, data_path)
    data_path.write_text('["not", "a", "secret-map"]', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid structure"):
        vault.list()


def test_web_fetch_rejects_embedded_credentials() -> None:
    safe, reason = _safe_public_url("https://user:secret@example.com/private")
    assert safe is False
    assert "credentials" in reason.lower()


def test_web_fetch_rejects_loopback_resolution() -> None:
    fake_address = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with mock.patch("app.tools.web_tools.socket.getaddrinfo", return_value=fake_address):
        safe, reason = _safe_public_url("https://example.test/")
    assert safe is False
    assert "private" in reason.lower() or "reserved" in reason.lower()


def test_web_fetch_accepts_public_resolution() -> None:
    fake_address = [(2, 1, 6, "", ("93.184.216.34", 443))]
    with mock.patch("app.tools.web_tools.socket.getaddrinfo", return_value=fake_address):
        safe, reason = _safe_public_url("https://example.test/")
    assert safe is True
    assert reason == ""


def _connector_hub(tmp_path: Path) -> ConnectorHub:
    vault = SecretVault(tmp_path / "security" / "vault.key", tmp_path / "data" / "vault.json")
    db = mock.Mock()
    db.create_connector.return_value = {"id": "connector-test"}
    return ConnectorHub(db, vault)


def test_connector_rejects_embedded_credentials(tmp_path: Path) -> None:
    hub = _connector_hub(tmp_path)
    result = hub.create("unsafe", "https://user:secret@example.test/api")
    assert result["ok"] is False
    assert "credentials" in result["error"].lower()
    hub.db.create_connector.assert_not_called()


def test_connector_rejects_private_resolution(tmp_path: Path) -> None:
    hub = _connector_hub(tmp_path)
    fake_address = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with mock.patch("app.connectors.socket.getaddrinfo", return_value=fake_address):
        result = hub.create("unsafe", "https://internal.example.test/api")
    assert result["ok"] is False
    assert "private" in result["error"].lower() or "reserved" in result["error"].lower()
    hub.db.create_connector.assert_not_called()


def test_connector_fails_closed_on_unresolved_host(tmp_path: Path) -> None:
    hub = _connector_hub(tmp_path)
    with mock.patch("app.connectors.socket.getaddrinfo", side_effect=OSError("dns unavailable")):
        result = hub.create("unknown", "https://unresolved.example.test/api")
    assert result["ok"] is False
    hub.db.create_connector.assert_not_called()


def test_connector_rejects_dangerous_http_methods(tmp_path: Path) -> None:
    hub = _connector_hub(tmp_path)
    fake_address = [(2, 1, 6, "", ("93.184.216.34", 443))]
    with mock.patch("app.connectors.socket.getaddrinfo", return_value=fake_address):
        result = hub.create("trace", "https://example.test/api", allowed_methods=["GET", "TRACE"])
    assert result["ok"] is False
    assert "unsupported" in result["error"].lower()
    hub.db.create_connector.assert_not_called()


def test_connector_accepts_public_allowlisted_configuration(tmp_path: Path) -> None:
    hub = _connector_hub(tmp_path)
    fake_address = [(2, 1, 6, "", ("93.184.216.34", 443))]
    with mock.patch("app.connectors.socket.getaddrinfo", return_value=fake_address):
        result = hub.create("public", "https://example.test/api", allowed_methods=["GET", "POST"])
    assert result["ok"] is True
    hub.db.create_connector.assert_called_once()


def test_workspace_rejects_symlinked_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "workspace"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError, match="symlink"):
        WorkspaceFS(linked)


def test_workspace_rejects_symlinked_path_component(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = workspace / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    fs = WorkspaceFS(workspace)
    with pytest.raises(ValueError, match="Symlinked"):
        fs.resolve("linked/file.txt")


def test_workspace_write_refuses_symlink_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    fs = WorkspaceFS(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    linked = workspace / "linked.txt"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError, match="Symlinked"):
        fs.resolve("linked.txt")
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_workspace_copy_rejects_source_tree_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    fs = WorkspaceFS(workspace)
    source = workspace / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (source / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    result = fs.copy_path("source", "copied")
    assert result["ok"] is False
    assert "symlink" in result["error"].lower()
    assert not (workspace / "copied").exists()


def test_workspace_delete_refuses_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    fs = WorkspaceFS(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve", encoding="utf-8")
    linked = workspace / "linked.txt"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    result = fs.delete_path("linked.txt")
    assert result["ok"] is False
    assert "symlink" in result["error"].lower()
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_workspace_upload_uses_unique_exclusive_names(tmp_path: Path) -> None:
    fs = WorkspaceFS(tmp_path / "workspace")
    first = fs.upload_bytes("report.txt", b"one")
    second = fs.upload_bytes("report.txt", b"two")
    assert first == "uploads/report.txt"
    assert second == "uploads/report_1.txt"
    assert (tmp_path / "workspace" / first).read_bytes() == b"one"
    assert (tmp_path / "workspace" / second).read_bytes() == b"two"
