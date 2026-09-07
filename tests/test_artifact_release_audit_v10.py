import subprocess

from app.artifact_release_audit_v10 import (
    audit_artifact_release_evidence,
    required_artifact_release_test_ids,
)
from app.artifact_release_ci_v10 import ArtifactReleaseCIError, run_artifact_release_ci


def test_artifact_release_audit_passes_only_with_all_exact_required_tests():
    required = required_artifact_release_test_ids()
    audit = audit_artifact_release_evidence(passed_test_ids=required)
    assert audit.ready is True
    assert audit.passing_families == 4
    assert audit.missing_test_ids == ()
    assert audit.failed_test_ids == ()


def test_artifact_release_audit_fails_closed_when_required_test_is_missing():
    required = list(required_artifact_release_test_ids())
    audit = audit_artifact_release_evidence(passed_test_ids=required[:-1])
    assert audit.ready is False
    assert len(audit.missing_test_ids) == 1


def test_artifact_release_audit_required_failure_wins_over_passed_claim():
    required = list(required_artifact_release_test_ids())
    failed = required[0]
    audit = audit_artifact_release_evidence(
        passed_test_ids=required,
        failed_test_ids=[failed],
    )
    assert audit.ready is False
    assert audit.failed_test_ids == (failed,)


def test_artifact_release_ci_executes_only_manifest_test_ids(tmp_path):
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    payload = run_artifact_release_ci(
        runner=runner,
        python_executable="python-test",
        repository_root=tmp_path,
    )
    required = list(required_artifact_release_test_ids())
    assert captured["command"] == ["python-test", "-m", "pytest", "-q", *required]
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
    assert payload["ready"] is True
    assert payload["benchmark"]["passing_families"] == 4


def test_artifact_release_ci_blocks_when_pytest_fails(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="failed")

    try:
        run_artifact_release_ci(runner=runner, repository_root=tmp_path)
    except ArtifactReleaseCIError:
        pass
    else:
        raise AssertionError("failed required release tests must block artifact readiness")
