import pytest

from app.coding_agent import CodingAgentPlanner


def test_change_set_defaults_validation_for_updates():
    changes = CodingAgentPlanner.build_change_set([
        {"path": "app/service.py", "action": "update", "rationale": "fix bug"}
    ])
    assert changes[0].validation == ["syntax_or_compile_check", "targeted_tests"]


def test_change_set_rejects_repo_escape():
    with pytest.raises(ValueError, match="inside the repository"):
        CodingAgentPlanner.build_change_set([
            {"path": "../outside.py", "action": "update"}
        ])


def test_change_set_rejects_duplicate_paths():
    with pytest.raises(ValueError, match="duplicate change"):
        CodingAgentPlanner.build_change_set([
            {"path": "app/a.py", "action": "update"},
            {"path": "app/a.py", "action": "update"},
        ])


def test_delete_requires_approval_in_summary():
    changes = CodingAgentPlanner.build_change_set([
        {"path": "app/legacy.py", "action": "delete", "risk": "low"}
    ])
    summary = CodingAgentPlanner.summarize(changes)
    assert summary["deletes"] == 1
    assert summary["requires_approval"] is True
    assert changes[0].risk == "medium"


def test_high_risk_change_requires_approval():
    changes = CodingAgentPlanner.build_change_set([
        {"path": "app/auth.py", "action": "update", "risk": "high", "validation": ["security_tests"]}
    ])
    summary = CodingAgentPlanner.summarize(changes)
    assert summary["high_risk"] == ["app/auth.py"]
    assert summary["requires_approval"] is True
