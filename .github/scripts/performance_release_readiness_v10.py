from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.performance_release_ci_v10 import render_performance_release_ci_json, run_performance_release_ci


if __name__ == "__main__":
    print(render_performance_release_ci_json(run_performance_release_ci(repository_root=ROOT)))
