from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from desktop.recovery import CrashRecoveryController, RecoveryPolicy, RecoveryStateError


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "VERSION").write_text("8.0.0-dev\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"mode":"desktop"}\n', encoding="utf-8")
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "project.txt").write_text("safe data\n", encoding="utf-8")
    return tmp_path


def test_crash_threshold_recommends_safe_mode(tmp_path: Path):
    controller = CrashRecoveryController(
        RecoveryPolicy(repository_root=make_repo(tmp_path), crash_threshold=3, crash_window_seconds=600)
    )
    controller.record_crash(exit_code=1, error="first", timestamp=1000)
    controller.record_crash(exit_code=2, error="second", timestamp=1010)
    assert controller.should_enter_safe_mode(now=1020) is False
    controller.record_crash(exit_code=3, error="third", timestamp=1015)
    assert controller.should_enter_safe_mode(now=1020) is True


def test_old_crashes_do_not_consume_current_budget(tmp_path: Path):
    controller = CrashRecoveryController(
        RecoveryPolicy(repository_root=make_repo(tmp_path), crash_threshold=2, crash_window_seconds=60)
    )
    controller.record_crash(exit_code=1, error="old", timestamp=100)
    controller.record_crash(exit_code=1, error="recent", timestamp=950)
    assert controller.should_enter_safe_mode(now=1000) is False


def test_corrupt_crash_journal_fails_closed_to_safe_mode(tmp_path: Path):
    controller = CrashRecoveryController(RecoveryPolicy(repository_root=make_repo(tmp_path)))
    controller.state_dir.mkdir(parents=True)
    controller.journal_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(RecoveryStateError, match="invalid crash journal entry"):
        controller.load_crashes()
    assert controller.should_enter_safe_mode(now=1000) is True


def test_recovery_paths_cannot_escape_repository(tmp_path: Path):
    controller = CrashRecoveryController(RecoveryPolicy(repository_root=make_repo(tmp_path)))
    with pytest.raises(RecoveryStateError, match="escapes repository root"):
        controller.create_backup(["../outside.txt"], timestamp=1)


def test_backup_has_integrity_sidecar_and_expected_members(tmp_path: Path):
    root = make_repo(tmp_path)
    controller = CrashRecoveryController(RecoveryPolicy(repository_root=root))
    archive, checksum = controller.create_backup(["config.json", "workspace/project.txt"], timestamp=1234)

    assert archive.is_file()
    assert checksum.is_file()
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == ["config.json", "workspace/project.txt"]
        assert bundle.read("workspace/project.txt") == b"safe data\n"

    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text(encoding="ascii") == f"{expected}  {archive.name}\n"


def test_backup_retention_removes_old_archive_and_checksum(tmp_path: Path):
    root = make_repo(tmp_path)
    controller = CrashRecoveryController(RecoveryPolicy(repository_root=root, backup_retention=2))
    created = []
    for stamp in (1, 2, 3):
        archive, checksum = controller.create_backup(["config.json"], timestamp=stamp)
        created.append((archive, checksum))

    archives = sorted(controller.backup_dir.glob("recovery-*.zip"))
    assert len(archives) == 2
    assert created[0][0].exists() is False
    assert created[0][1].exists() is False


def test_recovery_state_write_is_structured_and_bounded(tmp_path: Path):
    controller = CrashRecoveryController(RecoveryPolicy(repository_root=make_repo(tmp_path)))
    path = controller.write_recovery_state(safe_mode=True, reason=" repeated   crash \x00 loop ")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["safe_mode"] is True
    assert payload["reason"] == "repeated crash loop"


def test_diagnostics_exclude_environment_and_include_recovery_evidence(tmp_path: Path, monkeypatch):
    root = make_repo(tmp_path)
    monkeypatch.setenv("DPN_TEST_SECRET", "must-not-leak")
    controller = CrashRecoveryController(RecoveryPolicy(repository_root=root))
    controller.record_crash(exit_code=7, error="startup failure", timestamp=1000)
    target = controller.write_diagnostics(state="failed", pid=None, last_error="startup failure")
    text = target.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert "must-not-leak" not in text
    assert payload["version"] == "8.0.0-dev"
    assert payload["state"] == "failed"
    assert payload["recent_crashes"][-1]["exit_code"] == 7
