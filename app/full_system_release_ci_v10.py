from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app.full_system_release_v10 import audit_full_system_release, full_system_release_manifest


class FullSystemReleaseCIError(RuntimeError):
    pass


def run_full_system_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    manifest = full_system_release_manifest()
    if not manifest:
        raise FullSystemReleaseCIError("full-system release manifest is empty")
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    command = [python_executable or sys.executable, "-m", "pytest", "-q", *manifest.values()]
    completed = runner(command, cwd=str(root), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        output = "\n".join(part for part in ((completed.stdout or "").strip(), (completed.stderr or "").strip()) if part)
        if len(output) > 6000:
            output = output[-6000:]
        raise FullSystemReleaseCIError(f"Batch 15 required tests failed; readiness blocked\n{output}")
    audit = audit_full_system_release({family: True for family in manifest})
    if not audit["ready"]:
        raise FullSystemReleaseCIError("Batch 15 release audit failed closed")
    return {
        "schema_version": 1,
        "checkpoint": "v10.0.0-batch-15",
        "ready": True,
        "required_test_ids": list(manifest.values()),
        "audit": audit,
    }


def render_full_system_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["FullSystemReleaseCIError", "render_full_system_release_ci_json", "run_full_system_release_ci"]
