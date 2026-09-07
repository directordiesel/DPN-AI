from __future__ import annotations

import subprocess

import pytest

from app.performance_release_ci_v10 import PerformanceReleaseCIError, run_performance_release_ci
from app.performance_release_v10 import (
    PerformanceReleaseError,
    audit_performance_release,
    performance_release_manifest,
    require_performance_release,
)


def test_manifest_is_immutable_seven_family_release_contract() -> None:
    manifest = performance_release_manifest()
    assert list(manifest) == [
        "measurable_improvement_integrity",
        "benchmark_task_set_integrity",
        "quality_success_preservation",
        "resource_regression_integrity",
        "durable_evidence_integrity",
        "non_authorizing_evidence",
        "governed_profile_integrity",
    ]
    assert len(set(manifest.values())) == 7


def test_complete_release_evidence_is_ready_but_never_authorizing() -> None:
    manifest = performance_release_manifest()
    audit = require_performance_release({family: True for family in manifest})
    assert audit["ready"] is True
    assert audit["execution_authorized"] is False
    assert audit["checkpoint"] == "v10.0.0-batch-17"


def test_missing_failed_or_unexpected_release_evidence_fails_closed() -> None:
    manifest = performance_release_manifest()
    evidence = {family: True for family in manifest}
    evidence.pop("benchmark_task_set_integrity")
    evidence["quality_success_preservation"] = False
    evidence["invented_family"] = True
    audit = audit_performance_release(evidence)
    assert audit["ready"] is False
    assert "benchmark_task_set_integrity" in audit["missing_families"]
    assert "quality_success_preservation" in audit["failed_families"]
    assert audit["unexpected_families"] == ["invented_family"]
    with pytest.raises(PerformanceReleaseError):
        require_performance_release(evidence)


def test_ci_harness_runs_only_manifest_node_ids_and_returns_non_authorizing_audit(tmp_path) -> None:
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout="7 passed", stderr="")

    payload = run_performance_release_ci(runner=runner, python_executable="python-test", repository_root=tmp_path)
    manifest = performance_release_manifest()
    assert captured["command"] == ["python-test", "-m", "pytest", "-q", *manifest.values()]
    assert captured["cwd"] == str(tmp_path.resolve())
    assert payload["ready"] is True
    assert payload["audit"]["execution_authorized"] is False


def test_ci_harness_fails_closed_when_required_test_fails(tmp_path) -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="1 failed", stderr="boom")

    with pytest.raises(PerformanceReleaseCIError, match="readiness blocked"):
        run_performance_release_ci(runner=runner, repository_root=tmp_path)
