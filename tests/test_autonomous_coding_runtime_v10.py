import pytest

from app.autonomous_coding_runtime_v10 import (
    AutonomousCodingRuntime,
    CodingMission,
    CodingMissionError,
    CodingStage,
    ValidationEvidence,
)


def mission(**overrides):
    values = {
        "mission_id": "m-1",
        "repository": "directordiesel/DPN-AI",
        "objective": "repair and verify a repository change",
    }
    values.update(overrides)
    return CodingMission(**values)


def test_mission_starts_at_inspect_and_advances_in_order():
    item = AutonomousCodingRuntime().begin(mission())
    item.advance(CodingStage.PLAN)
    item.advance(CodingStage.ISOLATE)
    item.advance(CodingStage.EDIT)
    item.advance(CodingStage.VALIDATE)
    assert item.stage == CodingStage.VALIDATE


def test_invalid_transition_fails_closed():
    item = mission()
    with pytest.raises(CodingMissionError, match="invalid coding mission transition"):
        item.advance(CodingStage.READY)


def test_validation_failure_routes_to_diagnose():
    runtime = AutonomousCodingRuntime()
    item = mission(stage=CodingStage.VALIDATE)
    item.record_validation(ValidationEvidence("pytest", False, "1 failed"))
    assert runtime.route_validation_result(item) == CodingStage.DIAGNOSE


def test_validation_success_routes_to_review():
    runtime = AutonomousCodingRuntime()
    item = mission(stage=CodingStage.VALIDATE)
    item.record_validation(ValidationEvidence("pytest", True, "all passed"))
    assert runtime.route_validation_result(item) == CodingStage.REVIEW


def test_repair_budget_is_bounded_and_failure_is_recorded():
    item = mission(max_repairs=1, stage=CodingStage.REPAIR)
    item.record_repair()
    with pytest.raises(CodingMissionError, match="repair budget exhausted"):
        item.record_repair()
    assert item.stage == CodingStage.FAILED
    assert item.failure_reason == "repair budget exhausted"


def test_ready_requires_validation_review_security_and_ci():
    item = mission(stage=CodingStage.READY)
    item.record_validation(ValidationEvidence("pytest", True))
    item.mark_review(review_passed=True, security_passed=True)
    item.mark_ci(True)
    assert item.ready is True
    item.require_ready()


def test_ready_fails_closed_when_security_or_ci_evidence_is_missing():
    item = mission(stage=CodingStage.READY)
    item.record_validation(ValidationEvidence("pytest", True))
    item.mark_review(review_passed=True, security_passed=False)
    item.mark_ci(True)
    assert item.ready is False
    with pytest.raises(CodingMissionError, match="not ready"):
        item.require_ready()


def test_ci_failure_routes_back_to_diagnosis():
    runtime = AutonomousCodingRuntime()
    item = mission(stage=CodingStage.CI)
    item.mark_ci(False)
    assert runtime.route_ci_result(item) == CodingStage.DIAGNOSE


def test_empty_mission_identity_is_rejected():
    with pytest.raises(CodingMissionError, match="mission id"):
        AutonomousCodingRuntime().begin(mission(mission_id=""))
