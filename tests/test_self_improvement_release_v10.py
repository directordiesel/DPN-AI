import subprocess

import pytest

from app.self_improvement_release_ci_v10 import SelfImprovementReleaseCIError, run_self_improvement_release_ci
from app.self_improvement_release_v10 import audit_self_improvement_release, self_improvement_release_manifest


def test_release_audit_requires_every_exact_family() -> None:
    manifest = self_improvement_release_manifest()
    ready = audit_self_improvement_release({family: True for family in manifest})
    assert ready["ready"] is True
    assert ready["passed"] == ready["required"] == 4

    missing = dict((family, True) for family in manifest)
    missing.pop("rollback_approval_boundary")
    blocked = audit_self_improvement_release(missing)
    assert blocked["ready"] is False
    assert blocked["missing_families"] == ["rollback_approval_boundary"]


def test_release_audit_rejects_unexpected_or_failed_family() -> None:
    manifest = {family: True for family in self_improvement_release_manifest()}
    manifest["commit_binding"] = False
    manifest["invented"] = True
    audit = audit_self_improvement_release(manifest)
    assert audit["ready"] is False
    assert "commit_binding" in audit["failed_families"]
    assert audit["unexpected_families"] == ["invented"]


def test_release_ci_executes_only_immutable_manifest(tmp_path) -> None:
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout="4 passed", stderr="")

    payload = run_self_improvement_release_ci(runner=runner, python_executable="python", repository_root=tmp_path)
    assert payload["ready"] is True
    assert captured["command"][:4] == ["python", "-m", "pytest", "-q"]
    assert captured["command"][4:] == list(self_improvement_release_manifest().values())


def test_release_ci_fails_closed_on_pytest_failure(tmp_path) -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="failed", stderr="boom")

    with pytest.raises(SelfImprovementReleaseCIError, match="readiness blocked"):
        run_self_improvement_release_ci(runner=runner, repository_root=tmp_path)
