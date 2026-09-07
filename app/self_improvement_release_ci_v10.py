from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app.self_improvement_release_v10 import audit_self_improvement_release, self_improvement_release_manifest


class SelfImprovementReleaseCIError(RuntimeError):
    pass


def run_self_improvement_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    manifest = self_improvement_release_manifest()
    if not manifest:
        raise SelfImprovementReleaseCIError("self-improvement release manifest is empty")
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    command = [python_executable or sys.executable, "-m", "pytest", "-q", *manifest.values()]
    completed = runner(command, cwd=str(root), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        output = "\n".join(part for part in ((completed.stdout or "").strip(), (completed.stderr or "").strip()) if part)
        if len(output) > 6000:
            output = output[-6000:]
        raise SelfImprovementReleaseCIError(f"Batch 14 required tests failed; readiness blocked\n{output}")
    audit = audit_self_improvement_release({family: True for family in manifest})
    if not audit["ready"]:
        raise SelfImprovementReleaseCIError("Batch 14 release audit failed closed")
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-14",
        "ready": True,
        "required_test_count": len(manifest),
        "required_test_ids": list(manifest.values()),
        "audit": audit,
    }


def render_self_improvement_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["SelfImprovementReleaseCIError", "render_self_improvement_release_ci_json", "run_self_improvement_release_ci"]
