from __future__ import annotations

import subprocess
from pathlib import Path


SENSITIVE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".enc"}
SENSITIVE_DIRS = {
    "runtime_logs",
    "install_logs",
}
SENSITIVE_PREFIXES = {
    "data",
    "workspace/generated",
    "workspace/uploads",
}
SENSITIVE_FILENAMES = {
    ".env",
}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def is_sensitive(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/").strip("/")
    path = Path(normalized)
    parts = normalized.split("/")

    if path.name in SENSITIVE_FILENAMES:
        return True
    lowered_name = path.name.lower()
    if lowered_name.endswith(".key") and (
        lowered_name.startswith("vault") or lowered_name.startswith("master")
    ):
        return True
    if any(part in SENSITIVE_DIRS for part in parts):
        return True
    if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in SENSITIVE_PREFIXES):
        if path.suffix.lower() in SENSITIVE_SUFFIXES or normalized.startswith("workspace/"):
            return True
    return False


def verify_version_consistency() -> None:
    version = Path("VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("VERSION is empty")
    readme = Path("README.md").read_text(encoding="utf-8")
    if version not in readme:
        raise SystemExit(f"README.md does not reference VERSION value {version!r}")
    print(f"README and VERSION agree: {version}")


def main() -> int:
    sensitive = sorted(path for path in tracked_files() if is_sensitive(path))
    if sensitive:
        print("Sensitive/runtime DPN AI files must not be tracked:")
        for path in sensitive:
            print(f" - {path}")
        return 1

    verify_version_consistency()
    print("DPN AI cross-platform repository guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
