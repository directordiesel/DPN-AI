from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_runtime_version_matches_version_file():
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', MAIN, flags=re.MULTILINE)
    assert match is not None, "APP_VERSION assignment missing from app/main.py"
    assert match.group(1) == VERSION, f"Runtime APP_VERSION {match.group(1)!r} does not match VERSION {VERSION!r}"


def test_ui_identifies_stable_core_version():
    assert f"STABLE CORE v{VERSION}" in INDEX


def test_ui_no_longer_advertises_v5_runtime():
    assert "v5.0.7" not in INDEX
