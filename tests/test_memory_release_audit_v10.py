from app.memory_release_audit_v10 import (
    MEMORY_RELEASE_TEST_MANIFEST,
    audit_memory_release_evidence,
    required_memory_release_test_ids,
)


def test_manifest_covers_every_memory_readiness_family():
    assert set(MEMORY_RELEASE_TEST_MANIFEST) == {
        "memory_scope_isolation",
        "memory_provenance_integrity",
        "memory_conflict_preservation",
        "memory_supersession_lineage",
        "memory_recovery_detection",
        "memory_retention_bounds",
        "memory_trusted_promotion",
        "memory_tool_authorization",
    }
    assert all(MEMORY_RELEASE_TEST_MANIFEST[family] for family in MEMORY_RELEASE_TEST_MANIFEST)


def test_complete_trusted_executed_test_evidence_passes_release_audit():
    required = required_memory_release_test_ids()
    result = audit_memory_release_evidence(passed_test_ids=required)
    assert result.ready is True
    assert result.reason == "memory release audit passed"
    assert result.missing_test_ids == ()
    assert result.failed_test_ids == ()
    assert result.readiness.ready is True
    assert result.readiness.passing_families == 8
    assert result.readiness.overall_success_rate == 1.0
    assert result.readiness.overall_quality_score == 1.0


def test_missing_executed_test_evidence_fails_closed():
    required = list(required_memory_release_test_ids())
    missing = required.pop()
    result = audit_memory_release_evidence(passed_test_ids=required)
    assert result.ready is False
    assert missing in result.missing_test_ids
    assert result.readiness.ready is False


def test_required_failure_blocks_release_even_if_also_claimed_passed():
    required = required_memory_release_test_ids()
    failed = required[0]
    result = audit_memory_release_evidence(passed_test_ids=required, failed_test_ids=[failed])
    assert result.ready is False
    assert result.failed_test_ids == (failed,)
    assert "required tests failed" in result.reason
    assert result.readiness.ready is False


def test_unrelated_test_failures_do_not_fabricate_required_memory_failure():
    required = required_memory_release_test_ids()
    result = audit_memory_release_evidence(
        passed_test_ids=required,
        failed_test_ids=["tests/test_unrelated.py::test_other"],
    )
    assert result.ready is True
    assert result.failed_test_ids == ()
