from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app.security_regression_release_v10 import (
    audit_security_regression_release,
    security_regression_release_manifest,
)


class SecurityRegressionReleaseCIError(RuntimeError):
    pass


def run_security_regression_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    manifest = security_regression_release_manifest()
    if not manifest:
        raise SecurityRegressionReleaseCIError("Batch 16 security/regression manifest is empty")
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    command = [python_executable or sys.executable, "-m", "pytest", "-q", *manifest.values()]
    completed = runner(command, cwd=str(root), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        output = "\n".join(
            part
            for part in ((completed.stdout or "").strip(), (completed.stderr or "").strip())
            if part
        )
        if len(output) > 6000:
            output = output[-6000:]
        raise SecurityRegressionReleaseCIError(
            "Batch 16 required security/regression tests failed; readiness blocked\n" + output
        )
    audit = audit_security_regression_release({family: True for family in manifest})
    if not audit["ready"] or audit["execution_authorized"] is not False:
        raise SecurityRegressionReleaseCIError("Batch 16 security/regression audit failed closed")
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-16",
        "ready": True,
        "required_test_ids": list(manifest.values()),
        "audit": audit,
    }


def render_security_regression_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "SecurityRegressionReleaseCIError",
    "render_security_regression_release_ci_json",
    "run_security_regression_release_ci",
]
