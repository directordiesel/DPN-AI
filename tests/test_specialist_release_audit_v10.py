from app.specialist_release_audit_v10 import (
    audit_specialist_release_evidence,
    required_specialist_release_test_ids,
)


def test_specialist_release_audit_requires_every_manifest_case():
    required = required_specialist_release_test_ids()
    assert len(required) == 5
    audit = audit_specialist_release_evidence(passed_test_ids=required)
    assert audit.ready is True
    assert audit.passing_families == 5
    assert audit.missing_test_ids == ()
    assert audit.failed_test_ids == ()


def test_specialist_release_audit_fails_closed_for_missing_case():
    required = required_specialist_release_test_ids()
    audit = audit_specialist_release_evidence(passed_test_ids=required[:-1])
    assert audit.ready is False
    assert audit.missing_test_ids == (required[-1],)


def test_specialist_release_audit_failure_overrides_pass_claim():
    required = required_specialist_release_test_ids()
    failed = required[0]
    audit = audit_specialist_release_evidence(
        passed_test_ids=required,
        failed_test_ids=[failed],
    )
    assert audit.ready is False
    assert audit.failed_test_ids == (failed,)
    assert audit.passing_families == 4
