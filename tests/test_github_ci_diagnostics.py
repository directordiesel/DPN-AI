from app.github_ci_diagnostics import GitHubCIDiagnostics


def test_infrastructure_failure_is_retryable():
    result = GitHubCIDiagnostics.classify("CI", "failure", logs="runner lost communication")
    assert result.category == "infrastructure"
    assert result.retryable is True


def test_security_failure_is_not_auto_bypassed():
    result = GitHubCIDiagnostics.classify("DPN Security Gate v2", "failure", logs="security gate rejected credential exposure")
    assert result.category == "security"
    assert result.retryable is False
    assert "do not bypass" in result.next_action


def test_unknown_failure_requests_more_evidence():
    result = GitHubCIDiagnostics.classify("CI", "failure", steps=[{"name": "mystery", "conclusion": "failure"}])
    assert result.category == "workflow_step"
    assert "inspect logs" in result.next_action
