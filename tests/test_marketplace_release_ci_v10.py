from __future__ import annotations

import subprocess

import pytest

from app.marketplace_release_ci_v10 import MarketplaceReleaseCIError, run_marketplace_release_ci


def test_marketplace_release_ci_reports_captured_pytest_failure(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="FAILED tests/example.py::test_gate - assertion failed\n", stderr="")

    with pytest.raises(MarketplaceReleaseCIError) as exc:
        run_marketplace_release_ci(runner=runner, python_executable="python", repository_root=tmp_path)

    message = str(exc.value)
    assert "release readiness remains blocked" in message
    assert "FAILED tests/example.py::test_gate" in message
    assert "python -m pytest -q" in message


def test_marketplace_release_ci_bounds_failure_output(tmp_path):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="x" * 8000, stderr="tail-error")

    with pytest.raises(MarketplaceReleaseCIError) as exc:
        run_marketplace_release_ci(runner=runner, python_executable="python", repository_root=tmp_path)

    message = str(exc.value)
    assert "truncated to final 6000 characters" in message
    assert "tail-error" in message
    assert len(message) < 7000
