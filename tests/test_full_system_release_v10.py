from __future__ import annotations

import subprocess

import pytest

from app.full_system_release_ci_v10 import FullSystemReleaseCIError, run_full_system_release_ci
from app.full_system_release_v10 import audit_full_system_release, full_system_release_manifest


def test_full_system_release_audit_requires_exact_manifest() -> None:
    manifest = full_system_release_manifest()
    ready = audit_full_system_release({family: True for family in manifest})
    assert ready["ready"] is True
    assert ready["passed"] == ready["required"] == 6

    missing = {family: True for family in manifest}
    missing.pop("approval_boundary_preservation")
    blocked = audit_full_system_release(missing)
    assert blocked["ready"] is False
    assert blocked["missing_families"] == ["approval_boundary_preservation"]


def test_full_system_release_audit_rejects_failed_or_unexpected_family() -> None:
    results = {family: True for family in full_system_release_manifest()}
    results["subsystem_completeness"] = False
    results["invented"] = True
    audit = audit_full_system_release(results)
    assert audit["ready"] is False
    assert "subsystem_completeness" in audit["failed_families"]
    assert audit["unexpected_families"] == ["invented"]


def test_full_system_release_ci_executes_only_exact_manifest(tmp_path) -> None:
    captured: dict[str, object] = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout="6 passed", stderr="")

    payload = run_full_system_release_ci(runner=runner, python_executable="python", repository_root=tmp_path)
    assert payload["ready"] is True
    assert captured["command"][:4] == ["python", "-m", "pytest", "-q"]
    assert captured["command"][4:] == list(full_system_release_manifest().values())


def test_full_system_release_ci_fails_closed_on_pytest_failure(tmp_path) -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="failed", stderr="boom")

    with pytest.raises(FullSystemReleaseCIError, match="readiness blocked"):
        run_full_system_release_ci(runner=runner, repository_root=tmp_path)
