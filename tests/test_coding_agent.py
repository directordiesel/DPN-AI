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


def test_repository_map_deduplicates_dependencies_and_ignores_self_dependency():
    repository_map = CodingAgentPlanner.build_repository_map([
        {
            "path": "app/service.py",
            "dependencies": ["app/core.py", "app/core.py", "app/service.py"],
        },
        {"path": "app/core.py"},
    ])
    assert repository_map["app/service.py"].dependencies == ("app/core.py",)


def test_repository_map_rejects_duplicate_entries():
    with pytest.raises(ValueError, match="duplicate repository entry"):
        CodingAgentPlanner.build_repository_map([
            {"path": "app/service.py"},
            {"path": "app/service.py"},
        ])


def test_change_impact_finds_transitive_dependants_and_tests():
    repository_map = CodingAgentPlanner.build_repository_map([
        {"path": "app/core.py"},
        {"path": "app/service.py", "dependencies": ["app/core.py"]},
        {"path": "app/api.py", "dependencies": ["app/service.py"]},
        {"path": "tests/test_api.py", "kind": "test", "dependencies": ["app/api.py"]},
        {"path": "tests/test_other.py", "kind": "test", "dependencies": ["app/other.py"]},
    ])
    changes = CodingAgentPlanner.build_change_set([
        {"path": "app/core.py", "action": "update"}
    ])

    impact = CodingAgentPlanner.analyze_change_impact(changes, repository_map)

    assert impact["dependants"] == ["app/api.py", "app/service.py", "tests/test_api.py"]
    assert impact["targeted_tests"] == ["tests/test_api.py"]
    assert impact["unknown_changed"] == []


def test_targeted_test_selection_never_invents_missing_tests():
    repository_map = CodingAgentPlanner.build_repository_map([
        {"path": "app/core.py"},
        {"path": "app/service.py", "dependencies": ["app/core.py"]},
    ])
    changes = CodingAgentPlanner.build_change_set([
        {"path": "app/core.py", "action": "update"}
    ])

    assert CodingAgentPlanner.select_targeted_tests(changes, repository_map) == []


def test_patch_plan_flags_changed_paths_missing_from_repository_map():
    repository_map = CodingAgentPlanner.build_repository_map([
        {"path": "app/core.py"},
    ])
    changes = CodingAgentPlanner.build_change_set([
        {"path": "app/new_service.py", "action": "create"}
    ])

    plan = CodingAgentPlanner.build_patch_plan(changes, repository_map)

    assert plan["impact"]["unknown_changed"] == ["app/new_service.py"]
    assert plan["unknown_paths_require_review"] is True
    assert plan["validation"] == ["syntax_or_compile_check", "targeted_tests"]


def test_self_review_passes_when_changes_and_evidence_match_plan():
    changes = CodingAgentPlanner.build_change_set([
        {
            "path": "app/service.py",
            "action": "update",
            "validation": ["targeted_tests", "security_tests"],
        }
    ])

    review = CodingAgentPlanner.self_review(
        changes,
        ["app/service.py"],
        {"targeted_tests": True, "security_tests": True},
    )

    assert review["passed"] is True
    assert review["missing_planned_changes"] == []
    assert review["unexpected_changes"] == []
    assert review["failed_checks"] == []
    assert review["missing_evidence"] == []


def test_self_review_fails_closed_on_unexpected_change_or_missing_evidence():
    changes = CodingAgentPlanner.build_change_set([
        {
            "path": "app/service.py",
            "action": "update",
            "validation": ["targeted_tests", "security_tests"],
        }
    ])

    review = CodingAgentPlanner.self_review(
        changes,
        ["app/service.py", "app/unplanned.py"],
        {"targeted_tests": True},
    )

    assert review["passed"] is False
    assert review["unexpected_changes"] == ["app/unplanned.py"]
    assert review["missing_evidence"] == ["security_tests"]


def test_self_review_preserves_approval_signal_for_high_risk_change():
    changes = CodingAgentPlanner.build_change_set([
        {
            "path": "app/auth.py",
            "action": "update",
            "risk": "high",
            "validation": ["security_tests"],
        }
    ])

    review = CodingAgentPlanner.self_review(
        changes,
        ["app/auth.py"],
        {"security_tests": True},
    )

    assert review["passed"] is True
    assert review["requires_approval"] is True
