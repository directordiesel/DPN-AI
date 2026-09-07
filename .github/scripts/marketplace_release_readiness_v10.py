from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.marketplace_release_ci_v10 import render_marketplace_release_ci_json, run_marketplace_release_ci


def main() -> int:
    payload = run_marketplace_release_ci(repository_root=REPOSITORY_ROOT)
    print(render_marketplace_release_ci_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
