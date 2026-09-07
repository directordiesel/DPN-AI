from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from app.artifact_release_audit_v10 import (
    audit_artifact_release_evidence,
    required_artifact_release_test_ids,
)


class ArtifactReleaseCIError(RuntimeError):
    """Raised when trusted Batch 9 artifact release verification cannot complete."""


def run_artifact_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    test_ids: Sequence[str] = required_artifact_release_test_ids()
    if not test_ids:
        raise ArtifactReleaseCIError("artifact release test manifest is empty")

    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    executable = python_executable or sys.executable
    command = [executable, "-m", "pytest", "-q", *test_ids]
    completed = runner(
        command,
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ArtifactReleaseCIError(
            "required artifact release tests failed; release readiness remains blocked"
        )

    audit = audit_artifact_release_evidence(passed_test_ids=test_ids)
    if not audit.ready:
        raise ArtifactReleaseCIError(f"artifact release audit did not pass: {audit.reason}")

    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-9",
        "ready": True,
        "required_test_count": len(audit.required_test_ids),
        "required_test_ids": list(audit.required_test_ids),
        "missing_test_ids": list(audit.missing_test_ids),
        "failed_test_ids": list(audit.failed_test_ids),
        "benchmark": {
            "passing_families": audit.passing_families,
            "required_families": 4,
            "failing_families": list(audit.failing_families),
        },
    }


def render_artifact_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ArtifactReleaseCIError",
    "render_artifact_release_ci_json",
    "run_artifact_release_ci",
]
