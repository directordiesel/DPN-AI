from app.voice_release_audit_v10 import audit_voice_release_evidence, required_voice_release_test_ids


def test_voice_release_audit_requires_all_exact_cases():
    required = required_voice_release_test_ids()
    result = audit_voice_release_evidence(passed_test_ids=required)
    assert result.ready is True
    assert result.passing_families == 5
    assert result.missing_test_ids == ()
    assert result.failed_test_ids == ()


def test_voice_release_audit_fails_closed_on_missing_case():
    required = required_voice_release_test_ids()
    result = audit_voice_release_evidence(passed_test_ids=required[:-1])
    assert result.ready is False
    assert result.missing_test_ids


def test_voice_release_audit_failure_overrides_pass_claim():
    required = required_voice_release_test_ids()
    failed = required[0]
    result = audit_voice_release_evidence(passed_test_ids=required, failed_test_ids=[failed])
    assert result.ready is False
    assert result.failed_test_ids == (failed,)
