from pathlib import Path

import pytest

from app.tools.filesystem import WorkspaceFS
from app.tools.shell import SafeCommandRunner


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