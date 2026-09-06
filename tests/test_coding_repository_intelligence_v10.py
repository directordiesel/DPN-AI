import pytest

from app.coding_repository_intelligence_v10 import (
    CodingRepositoryError,
    DiffRisk,
    RepositoryFile,
    RepositoryIntelligence,
    RepositoryMap,
    RiskFinding,
)


def repo() -> RepositoryMap:
    return RepositoryMap.build(
        [
            RepositoryFile("app/alpha.py", 100, "python"),
            RepositoryFile("app/beta.py", 100, "python"),
            RepositoryFile("tests/test_alpha.py", 100, "python"),
            RepositoryFile("tests/test_beta_extra.py", 100, "python"),
            RepositoryFile(".github/workflows/ci.yml", 100, "yaml"),
        ]
    )


def test_repository_map_rejects_duplicate_paths() -> None:
    with pytest.raises(CodingRepositoryError, match="duplicate"):
        RepositoryMap.build([RepositoryFile("app/a.py"), RepositoryFile("app/a.py")])


def test_repository_map_rejects_escape_paths() -> None:
    with pytest.raises(CodingRepositoryError, match="inside"):
        RepositoryMap.build([RepositoryFile("../escape.py")])


def test_change_impact_selects_existing_related_tests() -> None:
    impact = RepositoryIntelligence.analyze_change_impact(repo(), ["app/alpha.py"])
    assert impact.changed_files == ("app/alpha.py",)
    assert impact.directly_affected_tests == ("tests/test_alpha.py",)
    assert impact.missing_paths == ()


def test_change_impact_never_invents_missing_file() -> None:
    impact = RepositoryIntelligence.analyze_change_impact(repo(), ["app/missing.py"])
    assert impact.changed_files == ()
    assert impact.directly_affected_tests == ()
    assert impact.missing_paths == ("app/missing.py",)


def test_sensitive_workflow_change_is_high_risk_and_requires_approval() -> None:
    assessment = RepositoryIntelligence.classify_diff_risk([".github/workflows/ci.yml"], added_lines=2)
    assert assessment.risk == DiffRisk.HIGH
    assert assessment.approval_required is True


def test_large_diff_is_high_risk() -> None:
    assessment = RepositoryIntelligence.classify_diff_risk(["app/alpha.py"], added_lines=900, deleted_lines=150)
    assert assessment.risk == DiffRisk.HIGH


def test_critical_security_finding_forces_critical_risk() -> None:
    assessment = RepositoryIntelligence.classify_diff_risk(
        ["app/alpha.py"],
        security_findings=[RiskFinding("secret", DiffRisk.CRITICAL, "app/alpha.py", "secret exposure")],
    )
    assert assessment.risk == DiffRisk.CRITICAL
    assert assessment.approval_required is True


def test_pr_evidence_ready_requires_all_verification_layers() -> None:
    impact = RepositoryIntelligence.analyze_change_impact(repo(), ["app/alpha.py"])
    risk = RepositoryIntelligence.classify_diff_risk(["app/alpha.py"], added_lines=10)
    evidence = RepositoryIntelligence.build_pr_evidence(
        impact=impact,
        risk=risk,
        validation_passed=True,
        self_review_passed=True,
        security_review_passed=True,
        ci_passed=True,
    )
    assert evidence.ready is True
    assert evidence.selected_tests == ("tests/test_alpha.py",)


def test_pr_evidence_fails_closed_on_missing_paths() -> None:
    impact = RepositoryIntelligence.analyze_change_impact(repo(), ["app/missing.py"])
    risk = RepositoryIntelligence.classify_diff_risk(["app/missing.py"], added_lines=1)
    evidence = RepositoryIntelligence.build_pr_evidence(
        impact=impact,
        risk=risk,
        validation_passed=True,
        self_review_passed=True,
        security_review_passed=True,
        ci_passed=True,
    )
    assert evidence.ready is False
    assert "missing:app/missing.py" in evidence.unresolved_findings


def test_pr_evidence_fails_when_ci_or_review_is_not_green() -> None:
    impact = RepositoryIntelligence.analyze_change_impact(repo(), ["app/alpha.py"])
    risk = RepositoryIntelligence.classify_diff_risk(["app/alpha.py"])
    evidence = RepositoryIntelligence.build_pr_evidence(
        impact=impact,
        risk=risk,
        validation_passed=True,
        self_review_passed=False,
        security_review_passed=True,
        ci_passed=False,
    )
    assert evidence.ready is False
