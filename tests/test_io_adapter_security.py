from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.browser_adapter import BrowserAdapter
from app.desktop_adapter import DesktopAdapter
from app.media import MediaTools


def test_browser_rejects_embedded_credentials(tmp_path: Path):
    adapter = BrowserAdapter(tmp_path / "workspace", allow_private_network=True)
    ok, reason = adapter._validate_url("https://user:password@example.com/path")
    assert ok is False
    assert "credentials" in reason.lower()


def test_browser_public_mode_rejects_private_host(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.browser_adapter.ConnectorHub._is_private_host", lambda host: host == "internal.test")
    adapter = BrowserAdapter(tmp_path / "workspace", allow_private_network=False)
    ok, reason = adapter._validate_url("https://internal.test/")
    assert ok is False
    assert "private" in reason.lower()


def test_browser_screenshot_target_rejects_symlink(tmp_path: Path):
    workspace = tmp_path / "workspace"
    adapter = BrowserAdapter(workspace, allow_private_network=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    linked = adapter.output_dir / "capture.png"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError):
        adapter._output_path("capture.png")


def test_desktop_screenshot_target_rejects_symlink(tmp_path: Path):
    workspace = tmp_path / "workspace"
    adapter = DesktopAdapter(workspace)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    linked = adapter.output_dir / "screen.png"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError):
        adapter._output_path("screen.png", "screen.png")


def test_media_rejects_symlinked_source(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"media")
    linked = workspace / "linked.mp4"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    media = MediaTools(workspace)
    with pytest.raises(ValueError):
        media._source("linked.mp4")


def test_media_extra_args_require_allowlisted_option_value_pairs(tmp_path: Path):
    media = MediaTools(tmp_path / "workspace")
    ok, parsed = media._extra_ffmpeg_args(["-crf", "23", "-preset", "medium", "-movflags", "+faststart"])
    assert ok is True
    assert parsed == ["-crf", "23", "-preset", "medium", "-movflags", "+faststart"]

    for values in (
        ["https://attacker.invalid/output"],
        ["-i", "https://attacker.invalid/file"],
        ["-crf", "999"],
        ["-preset", "arbitrary"],
        ["-movflags", "+use_metadata_tags"],
        ["-crf"],
    ):
        allowed, _ = media._extra_ffmpeg_args(values)
        assert allowed is False


def test_media_output_target_rejects_symlink(tmp_path: Path):
    workspace = tmp_path / "workspace"
    media = MediaTools(workspace)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    linked = media.output_dir / "render.mp4"
    try:
        linked.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")
    with pytest.raises(ValueError):
        media._target("render.mp4", media.VIDEO_SUFFIXES)


def test_media_rejects_workspace_shadowed_ffmpeg(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake = workspace / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    fake.write_text("fake", encoding="utf-8")
    try:
        fake.chmod(0o755)
    except OSError:
        pass
    monkeypatch.setenv("PATH", str(workspace))
    media = MediaTools(workspace)
    assert media._tool("ffmpeg") is None
