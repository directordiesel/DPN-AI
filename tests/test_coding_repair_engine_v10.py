import pytest

from app.autonomous_coding_runtime_v10 import CodingMission, CodingMissionError, CodingStage
from app.coding_repair_engine_v10 import (
    ChangePlanStep,
    CodingRepairEngine,
    FailureKind,
    RepairDisposition,
    ValidationResult,
)
from app.coding_repository_intelligence_v10 import DiffRisk


def mission(max_repairs: int = 3) -> CodingMission:
    return CodingMission("m-1", "directordiesel/DPN-AI", "repair failing code", max_repairs=max_repairs)


def test_change_plan_requires_contiguous_unique_order():
    plan = CodingRepairEngine.build_change_plan([
        ChangePlanStep(2, "tests/test_x.py", "update", "adjust regression test"),
        ChangePlanStep(1, "app/x.py", "update", "fix implementation", ("tests/test_x.py",)),
    ])
    assert [step.order for step in plan] == [1, 2]

    with pytest.raises(CodingMissionError, match="unique"):
        CodingRepairEngine.build_change_plan([
            ChangePlanStep(1, "app/a.py", "update", "a"),
            ChangePlanStep(1, "app/b.py", "update", "b"),
        ])

    with pytest.raises(CodingMissionError, match="contiguous"):
        CodingRepairEngine.build_change_plan([
            ChangePlanStep(2, "app/a.py", "update", "a"),
        ])


def test_validation_results_are_recorded_and_fail_closed():
    m = mission()
    passed = CodingRepairEngine.record_validation_results(
        m,
        [
            ValidationResult("compile", True, "ok", 0),
            ValidationResult("pytest", False, "1 failed", 1),
        ],
    )
    assert passed is False
    assert [item.name for item in m.evidence] == ["compile", "pytest"]
    assert m.evidence[-1].passed is False


def test_diagnosis_classifies_common_failure_types():
    assert CodingRepairEngine.diagnose([ValidationResult("compile", False, "SyntaxError: invalid syntax", 1)]).kind == FailureKind.SYNTAX
    assert CodingRepairEngine.diagnose([ValidationResult("tests", False, "pytest assertion failed", 1)]).kind == FailureKind.TEST
    assert CodingRepairEngine.diagnose([ValidationResult("security", False, "security vulnerability detected", 1)]).kind == FailureKind.SECURITY
    assert CodingRepairEngine.diagnose([ValidationResult("deps", False, "ModuleNotFoundError: x", 1)]).kind == FailureKind.DEPENDENCY


def test_low_risk_repairable_failure_routes_to_repair():
    m = mission()
    diagnosis = CodingRepairEngine.diagnose([ValidationResult("tests", False, "pytest failed", 1)])
    decision = CodingRepairEngine.decide_repair(m, diagnosis, diff_risk=DiffRisk.LOW)
    assert decision.disposition == RepairDisposition.REPAIR
    assert decision.next_stage == CodingStage.REPAIR


def test_high_risk_requires_approval():
    m = mission()
    diagnosis = CodingRepairEngine.diagnose([ValidationResult("tests", False, "pytest failed", 1)])
    decision = CodingRepairEngine.decide_repair(m, diagnosis, diff_risk=DiffRisk.HIGH)
    assert decision.disposition == RepairDisposition.ESCALATE

    approved = CodingRepairEngine.decide_repair(m, diagnosis, diff_risk=DiffRisk.HIGH, approval_granted=True)
    assert approved.disposition == RepairDisposition.REPAIR


def test_security_or_critical_failure_never_auto_repairs():
    m = mission()
    security = CodingRepairEngine.diagnose([ValidationResult("security", False, "secret exposed", 1)])
    decision = CodingRepairEngine.decide_repair(m, security, diff_risk=DiffRisk.LOW, approval_granted=True)
    assert decision.disposition == RepairDisposition.ESCALATE

    test_failure = CodingRepairEngine.diagnose([ValidationResult("tests", False, "pytest failed", 1)])
    critical = CodingRepairEngine.decide_repair(m, test_failure, diff_risk=DiffRisk.CRITICAL, approval_granted=True)
    assert critical.disposition == RepairDisposition.ESCALATE


def test_repair_budget_exhaustion_fails_closed():
    m = mission(max_repairs=1)
    m.repair_attempts = 1
    diagnosis = CodingRepairEngine.diagnose([ValidationResult("tests", False, "pytest failed", 1)])
    decision = CodingRepairEngine.decide_repair(m, diagnosis, diff_risk=DiffRisk.LOW)
    assert decision.disposition == RepairDisposition.FAIL
    assert "budget" in decision.reason


def test_unknown_failure_without_evidence_is_not_auto_repaired():
    m = mission()
    diagnosis = CodingRepairEngine.diagnose([])
    decision = CodingRepairEngine.decide_repair(m, diagnosis, diff_risk=DiffRisk.LOW)
    assert decision.disposition == RepairDisposition.FAIL
