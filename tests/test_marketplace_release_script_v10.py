from __future__ import annotations

import runpy
import sys
from pathlib import Path


def test_marketplace_release_readiness_script_bootstraps_repository_root(monkeypatch):
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / ".github" / "scripts" / "marketplace_release_readiness_v10.py"
    scripts_dir = script.parent

    monkeypatch.setattr(sys, "path", [str(scripts_dir)])
    namespace = runpy.run_path(str(script), run_name="marketplace_release_readiness_v10_test")

    assert namespace["REPOSITORY_ROOT"] == repository_root
    assert sys.path[0] == str(repository_root)
    assert "run_marketplace_release_ci" in namespace
