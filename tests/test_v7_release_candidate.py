from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_v7_release_candidate_has_required_foundations():
    required = [
        "plugins/project_intelligence_v7.py",
        "plugins/self_verification_v7.py",
        "plugins/security_qa_v7.py",
        "tests/test_v7_project_intelligence.py",
        "tests/test_v7_self_verification.py",
        "tests/test_v7_security_qa.py",
        "tests/test_v7_version_consistency.py",
    ]
    missing = [path for path in required if not (ROOT / path).is_file()]
    assert not missing, f"Missing v7 release foundations: {missing}"


def test_v7_release_candidate_runtime_version_matches_version_file():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', main, flags=re.MULTILINE)
    assert match is not None, "APP_VERSION assignment missing"
    assert match.group(1) == version


def test_temporary_alignment_workflow_is_not_part_of_release_candidate():
    assert not (ROOT / ".github" / "workflows" / "v7-version-alignment.yml").exists()
