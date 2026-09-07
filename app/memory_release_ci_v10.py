from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

from app.memory_release_audit_v10 import (
    audit_memory_release_evidence,
    required_memory_release_test_ids,
)


class MemoryReleaseCIError(RuntimeError):
    """Raised when trusted Batch 8 memory release verification cannot complete."""


def run_memory_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    """Execute the exact memory release manifest and return deterministic evidence.

    The test IDs come only from the immutable release manifest. A caller cannot
    substitute arbitrary tests or self-assert passes. Pytest exit code zero is the
    trusted execution signal that every selected manifest node passed.
    """

    test_ids: Sequence[str] = required_memory_release_test_ids()
    if not test_ids:
        raise MemoryReleaseCIError("memory release test manifest is empty")

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
        raise MemoryReleaseCIError(
            "required memory release tests failed; release readiness remains blocked"
        )

    audit = audit_memory_release_evidence(passed_test_ids=test_ids)
    if not audit.ready:
        raise MemoryReleaseCIError(f"memory release audit did not pass: {audit.reason}")

    payload = {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-8",
        "ready": True,
        "required_test_count": len(audit.required_test_ids),
        "required_test_ids": list(audit.required_test_ids),
        "missing_test_ids": list(audit.missing_test_ids),
        "failed_test_ids": list(audit.failed_test_ids),
        "benchmark": {
            "passing_families": audit.readiness.passing_families,
            "required_families": list(audit.readiness.required_families),
            "evaluated_samples": audit.readiness.evaluated_samples,
            "overall_success_rate": audit.readiness.overall_success_rate,
            "overall_quality_score": audit.readiness.overall_quality_score,
        },
    }
    return payload


def render_memory_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "MemoryReleaseCIError",
    "render_memory_release_ci_json",
    "run_memory_release_ci",
]
