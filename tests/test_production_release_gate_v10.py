from __future__ import annotations

import subprocess

import pytest

from app.production_release_ci_v10 import ProductionReleaseCIError, run_production_release_ci
from app.production_release_gate_v10 import (
    ProductionReleaseGateError,
    audit_production_release_gate,
    production_release_manifest,
    require_production_release_gate,
)


def test_batch18_manifest_is_exact_nine_family_contract() -> None:
    manifest = production_release_manifest()
    assert list(manifest) == [
        "stable_version_identity",
        "exact_commit_binding",
        "validation_gate_integrity",
        "strict_gate_boolean_integrity",
        "release_artifact_contract",
        "immutable_release_target",
        "non_authorizing_release_evidence",
        "deterministic_commit_bound_evidence",
        "active_version_surface_coherence",
    ]
    assert len(set(manifest.values())) == 9


def test_complete_batch18_manifest_is_ready_but_non_authorizing() -> None:
    manifest = production_release_manifest()
    audit = require_production_release_gate({family: True for family in manifest})
    assert audit["ready"] is True
    assert audit["execution_authorized"] is False
    assert audit["release_publish_authorized"] is False
    assert audit["checkpoint"] == "v10.0.0-batch-18-production-readiness"


def test_missing_failed_or_unexpected_batch18_evidence_fails_closed() -> None:
    manifest = production_release_manifest()
    evidence = {family: True for family in manifest}
    evidence.pop("stable_version_identity")
    evidence["release_artifact_contract"] = False
    evidence["candidate_invented_family"] = True
    audit = audit_production_release_gate(evidence)
    assert audit["ready"] is False
    assert "stable_version_identity" in audit["missing_families"]
    assert "release_artifact_contract" in audit["failed_families"]
    assert audit["unexpected_families"] == ["candidate_invented_family"]
    with pytest.raises(ProductionReleaseGateError):
        require_production_release_gate(evidence)


def test_truthy_non_boolean_batch18_evidence_fails_closed() -> None:
    manifest = production_release_manifest()
    evidence = {family: True for family in manifest}
    evidence["exact_commit_binding"] = 1
    assert audit_production_release_gate(evidence)["ready"] is False


def test_batch18_ci_harness_runs_only_exact_manifest_node_ids(tmp_path) -> None:
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout="9 passed", stderr="")

    payload = run_production_release_ci(
        runner=runner,
        python_executable="python-test",
        repository_root=tmp_path,
    )
    manifest = production_release_manifest()
    assert captured["command"] == ["python-test", "-m", "pytest", "-q", *manifest.values()]
    assert captured["cwd"] == str(tmp_path.resolve())
    assert payload["ready"] is True
    assert payload["audit"]["execution_authorized"] is False
    assert payload["audit"]["release_publish_authorized"] is False


def test_batch18_ci_harness_fails_closed_when_required_test_fails(tmp_path) -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="1 failed", stderr="boom")

    with pytest.raises(ProductionReleaseCIError, match="readiness blocked"):
        run_production_release_ci(runner=runner, repository_root=tmp_path)
