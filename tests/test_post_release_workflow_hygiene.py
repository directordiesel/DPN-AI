from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
LEGACY_V6_WORKFLOW = ROOT / ".github" / "workflows" / "publish-v6.yml"


def test_current_release_workflow_uses_strict_request_validator_and_repository_guard():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "validate_release_request.py" in text
    assert "ci_repository_guard.py" in text
    assert "Verify repository version matches requested release" not in text
    assert "^v[0-9]+([.][0-9]+){0,2}" not in text


def test_legacy_v6_publisher_is_non_publishing_and_read_only():
    text = LEGACY_V6_WORKFLOW.read_text(encoding="utf-8")
    assert "Legacy (Retired) DPN AI v6 Publisher" in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "gh release create" not in text
    assert "persist-credentials" not in text
