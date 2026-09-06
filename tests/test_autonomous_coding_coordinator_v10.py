import pytest

from app.autonomous_coding_coordinator_v10 import AutonomousCodingCoordinator
from app.autonomous_coding_runtime_v10 import CodingMission, CodingMissionError, CodingStage
from app.coding_ci_orchestrator_v10 import CIJobConclusion, CIJobEvidence
from app.coding_repair_engine_v10 import ChangePlanStep, ValidationResult
from app.coding_repository_intelligence_v10 import RepositoryFile, RepositoryMap


def repo_map():
    return RepositoryMap.build([
        RepositoryFile("app/service.py"),
        RepositoryFile("tests/test_service.py"),
    ])


def mission(max_repairs=2):
    return CodingMission("m1", "directordiesel/DPN-AI", "Fix service", max_repairs=max_repairs)


def test_prepare_builds_impact_plan_and_advances_to_validate():
    coordinator = AutonomousCodingCoordinator()
    m = mission()
    snapshot = coordinator.prepare(
        m,
        repository_map=repo_map(),
        changed_files=["app/service.py"],
        plan_steps=[ChangePlanStep(1, "app/service.py", "update", "fix defect")],
    )
    assert snapshot.stage == CodingStage.VALIDATE
    assert snapshot.impact.changed_files == ("app/service.py",)
    assert "tests/test_service.py" in snapshot.impact.directly_affected_tests


def test_prepare_rejects_missing_repository_path():
    coordinator = AutonomousCodingCoordinator()
    with pytest.raises(CodingMissionError, match="missing"):
        coordinator.prepare(
            mission(),
            repository_map=repo_map(),
            changed_files=["app/missing.py"],
            plan_steps=[ChangePlanStep(1, "app/missing.py", "update", "fix")],
        )


def test_validation_success_advances_to_review():
    coordinator = AutonomousCodingCoordinator()
    m = mission()
    snapshot = coordinator.prepare(
        m,
        repository_map=repo_map(),
        changed_files=["app/service.py"],
        plan_steps=[ChangePlanStep(1, "app/service.py", "update", "fix")],
    )
    passed, _ = coordinator.validate_or_route_repair(
        m,
        validation_results=[ValidationResult("pytest", True, "ok", 0)],
        risk=snapshot.risk,
    )
    assert passed is True
    assert m.stage == CodingStage.REVIEW


def test_validation_failure_routes_to_bounded_repair():
    coordinator = AutonomousCodingCoordinator()
    m = mission()
    snapshot = coordinator.prepare(
        m,
        repository_map=repo_map(),
        changed_files=["app/service.py"],
        plan_steps=[ChangePlanStep(1, "app/service.py", "update", "fix")],
    )
    passed, _ = coordinator.validate_or_route_repair(
        m,
        validation_results=[ValidationResult("pytest", False, "AssertionError test failed", 1)],
        risk=snapshot.risk,
    )
    assert passed is False
    assert m.stage == CodingStage.REPAIR
    assert m.repair_attempts == 1


def test_full_happy_path_reaches_ready():
    coordinator = AutonomousCodingCoordinator()
    m = mission()
    snapshot = coordinator.prepare(
        m,
        repository_map=repo_map(),
        changed_files=["app/service.py"],
        plan_steps=[ChangePlanStep(1, "app/service.py", "update", "fix")],
    )
    passed, _ = coordinator.validate_or_route_repair(
        m,
        validation_results=[ValidationResult("pytest", True, "ok", 0)],
        risk=snapshot.risk,
    )
    assert passed
    coordinator.record_review(m, review_passed=True, security_passed=True)
    result = coordinator.finalize_with_ci(
        m,
        impact=snapshot.impact,
        risk=snapshot.risk,
        ci_jobs=[CIJobEvidence("CI", CIJobConclusion.SUCCESS)],
        validation_passed=True,
    )
    assert result.ready is True
    assert m.stage == CodingStage.READY


def test_failed_ci_routes_back_to_repair():
    coordinator = AutonomousCodingCoordinator()
    m = mission()
    snapshot = coordinator.prepare(
        m,
        repository_map=repo_map(),
        changed_files=["app/service.py"],
        plan_steps=[ChangePlanStep(1, "app/service.py", "update", "fix")],
    )
    coordinator.validate_or_route_repair(
        m,
        validation_results=[ValidationResult("pytest", True, "ok", 0)],
        risk=snapshot.risk,
    )
    coordinator.record_review(m, review_passed=True, security_passed=True)
    result = coordinator.finalize_with_ci(
        m,
        impact=snapshot.impact,
        risk=snapshot.risk,
        ci_jobs=[CIJobEvidence("CI", CIJobConclusion.FAILURE, failed_step="pytest", log_excerpt="test failed")],
        validation_passed=True,
    )
    assert result.ready is False
    assert m.stage == CodingStage.REPAIR
