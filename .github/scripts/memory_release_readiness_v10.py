from __future__ import annotations

from pathlib import Path

from app.memory_release_ci_v10 import render_memory_release_ci_json, run_memory_release_ci


def main() -> int:
    payload = run_memory_release_ci(repository_root=Path(__file__).resolve().parents[2])
    print(render_memory_release_ci_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
