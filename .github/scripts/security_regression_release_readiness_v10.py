from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.security_regression_release_ci_v10 import run_security_regression_release_ci


if __name__ == "__main__":
    print(json.dumps(run_security_regression_release_ci(repository_root=ROOT), sort_keys=True, separators=(",", ":")))
