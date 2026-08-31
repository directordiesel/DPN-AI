from __future__ import annotations

import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.archive_tools import ArchiveTools


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def test_zip_traversal_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "escape.zip"
    _write_zip(archive_path, {"../escape.txt": b"nope"})
    tools = ArchiveTools(workspace)
    result = tools.extract("escape.zip")
    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()
    assert not (workspace.parent / "escape.txt").exists()


def test_zip_symlink_entry_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "link.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("linked")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")
    tools = ArchiveTools(workspace)
    inspected = tools.inspect("link.zip")
    assert inspected["ok"]
    assert inspected["unsafe_entries"] == ["linked"]
    extracted = tools.extract("link.zip")
    assert extracted["ok"] is False


def test_tar_symlink_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "link.tar"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("linked")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        archive.addfile(info)
    tools = ArchiveTools(workspace)
    result = tools.extract("link.tar")
    assert result["ok"] is False
    assert "unsafe" in result["error"].lower()


def test_runtime_byte_limit_is_enforced_and_partial_output_removed(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "large.zip"
    _write_zip(archive_path, {"payload.bin": b"A" * 4096})
    tools = ArchiveTools(workspace)
    result = tools.extract("large.zip", max_bytes=1024)
    assert result["ok"] is False
    assert "more than" in result["error"].lower() or "byte limit" in result["error"].lower()
    assert not (workspace / "generated" / "extracted" / "large").exists()


def test_symlinked_archive_input_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.zip"
    _write_zip(outside, {"ok.txt": b"hello"})
    linked = workspace / "linked.zip"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    tools = ArchiveTools(workspace)
    result = tools.extract("linked.zip")
    assert result["ok"] is False
    assert "symlink" in result["error"].lower() or "outside" in result["error"].lower()


def test_symlinked_extraction_root_is_rejected(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    generated = workspace / "generated"
    try:
        generated.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError, match="symlink"):
        ArchiveTools(workspace)


def test_overwrite_does_not_follow_symlink_destination(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    archive_path = workspace / "safe.zip"
    _write_zip(archive_path, {"file.txt": b"safe"})
    tools = ArchiveTools(workspace)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tools.output_dir / "safe"
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    result = tools.extract("safe.zip", overwrite=True)
    assert result["ok"] is False
    assert "symlink" in result["error"].lower()
    assert outside.exists()
