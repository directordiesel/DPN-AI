import pytest

from app.autonomous_coding_runtime_v10 import CodingMission, CodingStage
from app.coding_ci_orchestrator_v10 import (
    CIJobConclusion,
    CIJobEvidence,
    CodingCIOrchestrator,
)
from app.coding_repair_engine_v10 import FailureKind, RepairDisposition
from app.coding_repository_intelligence_v10 import DiffRisk, PullRequestEvidence


def mission() -> CodingMission:
    item = CodingMission("m1", "directordiesel/DPN-AI", "fix failing tests", max_repairs=2)
    item.stage = CodingStage.CI
    item.review_passed = True
    item.security_passed = True
    return item


def test_all_ci_jobs_pass_without_inventing_failure():
    result = CodingCIOrchestrator.analyze_jobs([
        CIJobEvidence("ubuntu", CIJobConclusion.SUCCESS),
        CIJobEvidence("windows", CIJobConclusion.SUCCESS),
    ])
    assert result.passed is True
    assert result.failed_jobs == ()
    assert result.diagnosis is None


def test_specific_test_failure_is_classified_from_ci_logs():
    result = CodingCIOrchestrator.analyze_jobs([
        CIJobEvidence(
            "ubuntu-tests",
            CIJobConclusion.FAILURE,
            failed_step="Run pytest",
            log_excerpt="pytest AssertionError in tests/test_router.py",
            affected_paths=("tests/test_router.py",),
        )
    ])
    assert result.passed is False
    assert result.diagnosis is not None
    assert result.diagnosis.kind == FailureKind.TEST
    assert result.diagnosis.affected_paths == ("tests/test_router.py",)


def test_unknown_ci_failure_falls_back_to_ci_diagnosis():
    result = CodingCIOrchestrator.analyze_jobs([
        CIJobEvidence("runner", CIJobConclusion.TIMED_OUT, log_excerpt="runner stopped unexpectedly")
    ])
    assert result.diagnosis is not None
    assert result.diagnosis.kind == FailureKind.CI
    assert result.diagnosis.repairable is True


def test_low_risk_failed_ci_routes_to_bounded_repair():
    item = mission()
    result = CodingCIOrchestrator.route(
        item,
        [CIJobEvidence("tests", CIJobConclusion.FAILURE, log_excerpt="pytest assert failed")],
        diff_risk=DiffRisk.LOW,
    )
    assert result.next_stage == CodingStage.REPAIR
    assert result.repair is not None
    assert result.repair.disposition == RepairDisposition.REPAIR
    assert item.repair_attempts == 1


def test_high_risk_ci_failure_requires_approval():
    item = mission()
    result = CodingCIOrchestrator.route(
        item,
        [CIJobEvidence("tests", CIJobConclusion.FAILURE, log_excerpt="pytest assert failed")],
        diff_risk=DiffRisk.HIGH,
        approval_granted=False,
    )
    assert result.next_stage == CodingStage.FAILED
    assert result.repair is not None
    assert result.repair.disposition == RepairDisposition.ESCALATE
    assert item.repair_attempts == 0


def test_security_failure_escalates_even_at_low_diff_risk():
    item = mission()
    result = CodingCIOrchestrator.route(
        item,
        [CIJobEvidence("security", CIJobConclusion.FAILURE, log_excerpt="security scan found exposed secret")],
        diff_risk=DiffRisk.LOW,
    )
    assert result.repair is not None
    assert result.repair.disposition == RepairDisposition.ESCALATE
    assert result.next_stage == CodingStage.FAILED


def test_ci_pass_only_marks_pr_ready_with_complete_evidence():
    item = mission()
    evidence = PullRequestEvidence(
        repository_mapped=True,
        changed_files=("app/example.py",),
        selected_tests=("tests/test_example.py",),
        validation_passed=True,
        self_review_passed=True,
        security_review_passed=True,
        ci_passed=True,
        diff_risk=DiffRisk.LOW,
    )
    result = CodingCIOrchestrator.route(
        item,
        [CIJobEvidence("ci", CIJobConclusion.SUCCESS)],
        diff_risk=DiffRisk.LOW,
        pr_evidence=evidence,
    )
    assert result.next_stage == CodingStage.READY
    assert result.pr_ready is True
    assert item.ci_passed is True


def test_ci_pass_without_review_security_evidence_does_not_claim_pr_ready():
    item = mission()
    item.review_passed = False
    item.security_passed = False
    result = CodingCIOrchestrator.route(
        item,
        [CIJobEvidence("ci", CIJobConclusion.SUCCESS)],
        diff_risk=DiffRisk.LOW,
    )
    assert result.pr_ready is False
    assert result.next_stage == CodingStage.REVIEW


def test_empty_ci_evidence_fails_closed():
    with pytest.raises(Exception, match="at least one CI job"):
        CodingCIOrchestrator.analyze_jobs([])
