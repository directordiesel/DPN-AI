from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from app.specialist_release_audit_v10 import (
    audit_specialist_release_evidence,
    required_specialist_release_test_ids,
)


class SpecialistReleaseCIError(RuntimeError):
    """Raised when trusted Batch 12 specialist verification cannot complete."""


def run_specialist_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    test_ids: Sequence[str] = required_specialist_release_test_ids()
    if not test_ids:
        raise SpecialistReleaseCIError("specialist release test manifest is empty")

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
        raise SpecialistReleaseCIError(
            "required specialist release tests failed; release readiness remains blocked"
        )

    audit = audit_specialist_release_evidence(passed_test_ids=test_ids)
    if not audit.ready:
        raise SpecialistReleaseCIError(f"specialist release audit did not pass: {audit.reason}")

    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-12",
        "ready": True,
        "required_test_count": len(audit.required_test_ids),
        "required_test_ids": list(audit.required_test_ids),
        "missing_test_ids": list(audit.missing_test_ids),
        "failed_test_ids": list(audit.failed_test_ids),
        "benchmark": {
            "passing_families": audit.passing_families,
            "required_families": 5,
            "failing_families": list(audit.failing_families),
        },
    }


def render_specialist_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["SpecialistReleaseCIError", "render_specialist_release_ci_json", "run_specialist_release_ci"]
