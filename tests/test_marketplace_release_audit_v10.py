from __future__ import annotations

from app.marketplace_release_audit_v10 import (
    audit_marketplace_release_evidence,
    required_marketplace_release_test_ids,
)


def test_marketplace_release_audit_passes_only_with_all_required_evidence():
    required = required_marketplace_release_test_ids()
    result = audit_marketplace_release_evidence(passed_test_ids=required)
    assert result.ready is True
    assert result.passing_families == 5
    assert result.missing_test_ids == ()
    assert result.failed_test_ids == ()


def test_marketplace_release_audit_fails_closed_when_evidence_is_missing():
    required = required_marketplace_release_test_ids()
    result = audit_marketplace_release_evidence(passed_test_ids=required[:-1])
    assert result.ready is False
    assert result.missing_test_ids
    assert "missing" in result.reason


def test_marketplace_release_audit_failed_test_overrides_pass_claim():
    required = required_marketplace_release_test_ids()
    failed = required[0]
    result = audit_marketplace_release_evidence(passed_test_ids=required, failed_test_ids=(failed,))
    assert result.ready is False
    assert result.failed_test_ids == (failed,)
    assert "failed" in result.reason
