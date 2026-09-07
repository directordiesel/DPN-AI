from __future__ import annotations

import subprocess

import pytest

from app.security_regression_release_ci_v10 import (
    SecurityRegressionReleaseCIError,
    run_security_regression_release_ci,
)
from app.security_regression_release_v10 import (
    SecurityRegressionReleaseError,
    audit_security_regression_release,
    require_security_regression_release,
    security_regression_release_manifest,
)


def test_security_regression_manifest_has_exact_mandatory_families() -> None:
    manifest = security_regression_release_manifest()
    assert tuple(manifest) == (
        "benchmark_evidence_integrity",
        "repository_path_containment",
        "ci_terminal_state_integrity",
        "model_provider_provenance",
        "connector_risk_contract",
        "approval_payload_binding",
        "approval_exact_reauthorization",
    )
    assert len(set(manifest.values())) == len(manifest)
    assert all(test_id.startswith("tests/") and "::test_" in test_id for test_id in manifest.values())


def test_release_audit_requires_every_family_and_never_authorizes_execution() -> None:
    manifest = security_regression_release_manifest()
    audit = require_security_regression_release({family: True for family in manifest})
    assert audit["ready"] is True
    assert audit["execution_authorized"] is False

    missing = dict.fromkeys(manifest, True)
    missing.pop("approval_payload_binding")
    with pytest.raises(SecurityRegressionReleaseError):
        require_security_regression_release(missing)

    failed = dict.fromkeys(manifest, True)
    failed["ci_terminal_state_integrity"] = False
    with pytest.raises(SecurityRegressionReleaseError):
        require_security_regression_release(failed)

    unexpected = dict.fromkeys(manifest, True)
    unexpected["caller_claimed_pass"] = True
    audit = audit_security_regression_release(unexpected)
    assert audit["ready"] is False
    assert audit["unexpected_families"] == ["caller_claimed_pass"]


def test_ci_harness_executes_only_exact_manifest_ids() -> None:
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="passed", stderr="")

    result = run_security_regression_release_ci(
        runner=runner,
        python_executable="python-test",
        repository_root=".",
    )
    manifest = security_regression_release_manifest()
    assert captured["command"] == ["python-test", "-m", "pytest", "-q", *manifest.values()]
    assert result["ready"] is True
    assert result["audit"]["execution_authorized"] is False


def test_ci_harness_fails_closed_and_surfaces_bounded_test_output() -> None:
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="X" * 7000, stderr="release-case-failed")

    with pytest.raises(SecurityRegressionReleaseCIError) as exc:
        run_security_regression_release_ci(runner=runner, repository_root=".")
    message = str(exc.value)
    assert "readiness blocked" in message
    assert "release-case-failed" in message
    assert len(message) < 6200
