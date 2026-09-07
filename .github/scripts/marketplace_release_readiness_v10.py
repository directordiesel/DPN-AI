from __future__ import annotations

from app.marketplace_release_ci_v10 import render_marketplace_release_ci_json, run_marketplace_release_ci


def main() -> int:
    payload = run_marketplace_release_ci()
    print(render_marketplace_release_ci_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
