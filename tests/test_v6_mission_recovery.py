from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "mission_recovery_v6.py"
spec = importlib.util.spec_from_file_location("mission_recovery_v6", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_recovery_plan_contains_evidence_driven_resume_and_completion_gate():
    plan = module.build_mission_recovery_plan(
        "Recover failed release mission",
        acceptance_criteria=["tests pass", "artifact exists"],
        checkpoint_evidence=["workspace/generated/app.zip"],
    )
    names = [stage["name"] for stage in plan["stages"]]
    assert names[:4] == ["recover_state", "validate_checkpoint", "classify_failure", "self_evaluate"]
    assert "bounded_repair" in names
    assert "completion_gate" in names
    assert plan["execution_policy"]["resume_from_verified_checkpoint"] is True
    assert plan["execution_policy"]["do_not_mark_complete_with_unverified_criteria"] is True


def test_repair_budget_is_bounded():
    assert module.build_mission_recovery_plan("x", max_repair_passes=99)["repair_budget"] == 5
    assert module.build_mission_recovery_plan("x", max_repair_passes=-3)["repair_budget"] == 0


def test_invalid_options_fall_back_safely():
    plan = module.build_mission_recovery_plan("x", mode="magic", failure_type="guess")
    assert plan["mode"] == "recover"
    assert plan["failure_type"] == "unknown"


def test_replan_can_be_disabled():
    plan = module.build_mission_recovery_plan("x", allow_replan=False)
    assert "replan" not in [stage["name"] for stage in plan["stages"]]


def test_completion_requires_evidence_for_every_criterion():
    result = module.evaluate_mission_completion([
        {"criterion": "tests", "status": "passed", "evidence": "pytest: 42 passed"},
        {"criterion": "artifact", "status": "passed", "evidence": "generated/app.zip"},
    ])
    assert result["complete"] is True


def test_completion_rejects_unverified_or_evidenceless_criteria():
    result = module.evaluate_mission_completion([
        {"criterion": "tests", "status": "passed", "evidence": ""},
        {"criterion": "artifact", "status": "unverified", "evidence": None},
    ])
    assert result["complete"] is False
    assert result["remaining"] == ["tests", "artifact"]


def test_empty_criteria_never_prove_completion():
    assert module.evaluate_mission_completion([])["complete"] is False


def test_operator_cancellation_and_shutdown_semantics_are_preserved():
    policy = module.build_mission_recovery_plan("x")["execution_policy"]
    assert policy["preserve_operator_cancellation"] is True
    assert policy["application_shutdown_is_pause_not_success"] is True
    assert policy["bounded_retries_only"] is True
