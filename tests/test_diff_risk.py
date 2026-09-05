from app.diff_risk import DiffRiskAnalyzer


def test_sensitive_workflow_change_requires_security_review():
    result = DiffRiskAnalyzer.analyze([
        {"filename": ".github/workflows/ci.yml", "additions": 5, "deletions": 2, "status": "modified"}
    ])
    assert result["risk_level"] == "high"
    assert result["requires_security_review"] is True
    assert result["requires_human_approval"] is True


def test_regular_small_change_is_low_risk():
    result = DiffRiskAnalyzer.analyze([
        {"filename": "app/widget.py", "additions": 12, "deletions": 3, "status": "modified"}
    ])
    assert result["risk_level"] == "low"
    assert result["requires_security_review"] is False


def test_file_deletion_requires_approval():
    result = DiffRiskAnalyzer.analyze([
        {"filename": "app/legacy.py", "additions": 0, "deletions": 40, "status": "removed"}
    ])
    assert result["requires_human_approval"] is True
