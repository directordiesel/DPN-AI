import subprocess

import pytest

from app.proactive_release_audit_v10 import audit_proactive_release_evidence, required_proactive_release_test_ids
from app.proactive_release_ci_v10 import ProactiveReleaseCIError, run_proactive_release_ci


def test_release_audit_requires_every_exact_manifest_test():
    required = required_proactive_release_test_ids()
    assert len(required) == 5

    ready = audit_proactive_release_evidence(passed_test_ids=required)
    assert ready.ready is True
    assert ready.passing_families == 5

    missing = audit_proactive_release_evidence(passed_test_ids=required[:-1])
    assert missing.ready is False
    assert missing.missing_test_ids == (required[-1],)


def test_failed_required_test_overrides_contradictory_pass_claim():
    required = required_proactive_release_test_ids()
    result = audit_proactive_release_evidence(passed_test_ids=required, failed_test_ids=[required[0]])
    assert result.ready is False
    assert result.failed_test_ids == (required[0],)


def test_ci_harness_executes_only_immutable_manifest(tmp_path):
    required = required_proactive_release_test_ids()
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="5 passed", stderr="")

    payload = run_proactive_release_ci(runner=runner, python_executable="python-test", repository_root=tmp_path)
    assert payload["ready"] is True
    assert payload["passing_families"] == 5
    assert len(calls) == 1
    assert calls[0][0] == ["python-test", "-m", "pytest", "-q", *required]


def test_ci_harness_blocks_failed_manifest_execution(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="failed", stderr="")

    with pytest.raises(ProactiveReleaseCIError, match="readiness remains blocked"):
        run_proactive_release_ci(runner=runner, repository_root=tmp_path)
