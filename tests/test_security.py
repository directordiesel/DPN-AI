from pathlib import Path

import pytest

from app.tools.filesystem import WorkspaceFS
from app.tools.shell import SafeCommandRunner
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
