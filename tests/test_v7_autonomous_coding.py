from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "autonomous_coding_v7.py"
spec = importlib.util.spec_from_file_location("autonomous_coding_v7", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_change_plan_is_repository_aware_and_bounded():
    plan = module.build_repository_change_plan(
        "Fix checkout regression",
        affected_files=[
            {"path": "app/service.py", "kind": "update", "reason": "fix logic"},
            {"path": "tests/test_service.py", "kind": "test", "reason": "regression"},
        ],
        test_targets=["pytest tests/test_service.py"],
        max_files=999,
    )
    assert plan["ok"] is True
    assert plan["file_budget"] == 100
    assert plan["execution_policy"]["map_repository_before_editing"] is True
    assert plan["execution_policy"]["trace_transitive_impact"] is True
    assert plan["execution_policy"]["no_test_weakening"] is True
    assert plan["execution_policy"]["no_security_gate_bypass"] is True
    assert [phase["name"] for phase in plan["phases"]][-1] == "completion_gate"


def test_empty_objective_is_rejected():
    result = module.build_repository_change_plan(" ")
    assert result["ok"] is False


def test_destructive_or_high_risk_change_requires_approval():
    destructive = module.build_repository_change_plan(
        "remove obsolete file",
        affected_files=[{"path": "old.py", "kind": "delete"}],
    )
    assert destructive["approval_required"] is True
    assert destructive["destructive_paths"] == ["old.py"]

    high_risk = module.build_repository_change_plan("security refactor", risk_level="high")
    assert high_risk["approval_required"] is True


def test_duplicate_files_are_collapsed_and_unknown_kind_is_safe_update():
    plan = module.build_repository_change_plan(
        "change files",
        affected_files=[
            {"path": "a.py", "kind": "magic"},
            {"path": "a.py", "kind": "delete"},
        ],
    )
    assert len(plan["changes"]) == 1
    assert plan["changes"][0]["kind"] == "update"


def test_coding_evidence_requires_files_and_passing_checks():
    ready = module.evaluate_coding_evidence(
        checks=[{"name": "pytest", "status": "passed", "evidence": "12 passed"}],
        changed_files=["app.py"],
    )
    assert ready["ready"] is True

    missing_files = module.evaluate_coding_evidence(
        checks=[{"name": "pytest", "status": "passed", "evidence": "12 passed"}],
        changed_files=[],
    )
    assert missing_files["ready"] is False

    failed = module.evaluate_coding_evidence(
        checks=[{"name": "pytest", "status": "failed", "evidence": "1 failed"}],
        changed_files=["app.py"],
    )
    assert failed["ready"] is False
    assert failed["failed_or_unverified"] == ["pytest"]
