from pathlib import Path
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
