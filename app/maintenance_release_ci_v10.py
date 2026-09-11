from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from app.maintenance_release_v10 import (
    CHECKPOINT,
    audit_maintenance_release,
    maintenance_release_manifest,
)


class MaintenanceReleaseCIError(RuntimeError):
    pass


def run_maintenance_release_ci(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    python_executable: str | None = None,
    repository_root: str | Path | None = None,
) -> dict:
    manifest = maintenance_release_manifest()
    if not manifest:
        raise MaintenanceReleaseCIError("v10.0.1 maintenance release manifest is empty")
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
        raise MaintenanceReleaseCIError(
            "v10.0.1 required maintenance tests failed; readiness blocked\n" + output
        )
    audit = audit_maintenance_release({family: True for family in manifest})
    if (
        not audit["ready"]
        or audit["execution_authorized"] is not False
        or audit["release_publish_authorized"] is not False
    ):
        raise MaintenanceReleaseCIError("v10.0.1 maintenance audit failed closed")
    return {
        "schema_version": 1,
        "checkpoint": CHECKPOINT,
        "ready": True,
        "required_test_ids": list(manifest.values()),
        "audit": audit,
    }


def render_maintenance_release_ci_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "MaintenanceReleaseCIError",
    "render_maintenance_release_ci_json",
    "run_maintenance_release_ci",
]
