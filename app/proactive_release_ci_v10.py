from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from app.proactive_release_audit_v10 import audit_proactive_release_evidence, required_proactive_release_test_ids


class ProactiveReleaseCIError(RuntimeError):
    pass


def run_proactive_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    test_ids: Sequence[str] = required_proactive_release_test_ids()
    if not test_ids:
        raise ProactiveReleaseCIError("proactive release test manifest is empty")
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    completed = runner(
        [python_executable or sys.executable, "-m", "pytest", "-q", *test_ids],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ProactiveReleaseCIError("required proactive release tests failed; readiness remains blocked")
    audit = audit_proactive_release_evidence(passed_test_ids=test_ids)
    if not audit.ready:
        raise ProactiveReleaseCIError(audit.reason)
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-11",
        "ready": True,
        "required_test_count": len(audit.required_test_ids),
        "required_test_ids": list(audit.required_test_ids),
        "missing_test_ids": list(audit.missing_test_ids),
        "failed_test_ids": list(audit.failed_test_ids),
        "passing_families": audit.passing_families,
        "required_families": len(audit.failing_families) + audit.passing_families,
    }


def render_proactive_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["ProactiveReleaseCIError", "render_proactive_release_ci_json", "run_proactive_release_ci"]
