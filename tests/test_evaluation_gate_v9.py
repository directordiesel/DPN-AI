import pytest

from app.evaluation_gate_v9 import (
    EvaluationCase,
    EvaluationResult,
    EvaluationStatus,
    V9EvaluationGate,
    default_v9_cases,
)


def _passing_results(cases):
    return [EvaluationResult(case.case_id, EvaluationStatus.PASS, "verified") for case in cases]


def test_default_gate_passes_when_all_cases_pass():
    cases = default_v9_cases()
    report = V9EvaluationGate(cases).evaluate(_passing_results(cases))
    assert report.passed is True
    assert report.weighted_score == 1.0
    assert report.critical_failures == ()
    assert report.missing_cases == ()


def test_critical_failure_blocks_release_even_with_high_score():
    cases = default_v9_cases()
    results = _passing_results(cases)
    index = next(i for i, item in enumerate(results) if item.case_id == "security.secret_and_injection_boundary")
    results[index] = EvaluationResult(results[index].case_id, EvaluationStatus.FAIL, "boundary regression")
    report = V9EvaluationGate(cases, minimum_score=0.5).evaluate(results)
    assert report.passed is False
    assert "security.secret_and_injection_boundary" in report.critical_failures


def test_missing_critical_case_fails_closed():
    cases = default_v9_cases()
    results = _passing_results(cases[:-1])
    report = V9EvaluationGate(cases).evaluate(results)
    assert report.passed is False
    assert "sdk.write_idempotency_and_approval" in report.missing_cases
    assert "sdk.write_idempotency_and_approval" in report.critical_failures


def test_skipped_critical_case_fails_closed():
    cases = (EvaluationCase("security.case", "security", True, 1),)
    report = V9EvaluationGate(cases).evaluate(
        [EvaluationResult("security.case", EvaluationStatus.SKIP, "runner unavailable")]
    )
    assert report.passed is False
    assert report.skipped_cases == 1
    assert report.critical_failures == ("security.case",)


def test_noncritical_failure_can_be_tolerated_by_score_policy():
    cases = (
        EvaluationCase("critical", "core", True, 9),
        EvaluationCase("optional", "ux", False, 1),
    )
    results = [
        EvaluationResult("critical", EvaluationStatus.PASS),
        EvaluationResult("optional", EvaluationStatus.FAIL),
    ]
    report = V9EvaluationGate(cases, minimum_score=0.9).evaluate(results)
    assert report.passed is True
    assert report.weighted_score == 0.9


def test_duplicate_cases_and_results_are_rejected():
    with pytest.raises(ValueError, match="duplicate evaluation case"):
        V9EvaluationGate((EvaluationCase("same", "one"), EvaluationCase("same", "two")))

    gate = V9EvaluationGate((EvaluationCase("one", "core"),))
    with pytest.raises(ValueError, match="duplicate evaluation result"):
        gate.evaluate(
            [
                EvaluationResult("one", EvaluationStatus.PASS),
                EvaluationResult("one", EvaluationStatus.PASS),
            ]
        )


def test_unknown_results_and_bad_weights_fail_closed():
    with pytest.raises(ValueError, match="positive integer"):
        V9EvaluationGate((EvaluationCase("one", "core", weight=0),))

    gate = V9EvaluationGate((EvaluationCase("one", "core"),))
    with pytest.raises(ValueError, match="unknown evaluation case"):
        gate.evaluate([EvaluationResult("other", EvaluationStatus.PASS)])


def test_domain_scores_are_deterministic():
    cases = (
        EvaluationCase("s1", "security", True, 2),
        EvaluationCase("s2", "security", False, 1),
        EvaluationCase("m1", "models", True, 1),
    )
    results = [
        EvaluationResult("s1", EvaluationStatus.PASS),
        EvaluationResult("s2", EvaluationStatus.FAIL),
        EvaluationResult("m1", EvaluationStatus.PASS),
    ]
    report = V9EvaluationGate(cases, minimum_score=0.7).evaluate(results)
    assert report.domain_scores["security"] == pytest.approx(2 / 3)
    assert report.domain_scores["models"] == 1.0
