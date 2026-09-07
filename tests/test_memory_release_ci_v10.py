from __future__ import annotations

import subprocess

import pytest

from app.memory_release_audit_v10 import required_memory_release_test_ids
from app.memory_release_ci_v10 import MemoryReleaseCIError, run_memory_release_ci


def test_ci_harness_executes_exact_manifest_and_reports_ready(tmp_path):
    seen = {}

    def runner(command, **kwargs):
        seen["command"] = list(command)
        seen["kwargs"] = dict(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    payload = run_memory_release_ci(
        runner=runner,
        python_executable="python-test",
        repository_root=tmp_path,
    )

    expected = list(required_memory_release_test_ids())
    assert seen["command"] == ["python-test", "-m", "pytest", "-q", *expected]
    assert seen["kwargs"]["cwd"] == str(tmp_path.resolve())
    assert payload["ready"] is True
    assert payload["required_test_count"] == len(expected)
    assert payload["benchmark"]["passing_families"] == 8
    assert payload["benchmark"]["overall_success_rate"] == 1.0
    assert payload["benchmark"]["overall_quality_score"] == 1.0


def test_ci_harness_fails_closed_when_any_selected_test_fails(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="failed", stderr="")

    with pytest.raises(MemoryReleaseCIError, match="required memory release tests failed"):
        run_memory_release_ci(runner=runner, repository_root=tmp_path)
