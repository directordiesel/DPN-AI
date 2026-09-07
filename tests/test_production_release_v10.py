import pytest

from app.production_release_v10 import (
    EXPECTED_STABLE_VERSION,
    ProductionReleaseError,
    REQUIRED_RELEASE_ARTIFACTS,
    REQUIRED_VALIDATION_GATES,
    evaluate_production_release,
)


def _gates():
    return {name: True for name in REQUIRED_VALIDATION_GATES}


def _artifacts():
    return {name: True for name in REQUIRED_RELEASE_ARTIFACTS}


def test_complete_release_candidate_is_ready_but_non_authorizing() -> None:
    result = evaluate_production_release(
        target_version=EXPECTED_STABLE_VERSION,
        commit_sha="a" * 40,
        validation_gates=_gates(),
        release_artifacts=_artifacts(),
    )

    assert result.target_tag == "v10.0.0"
    assert result.ready_for_version_promotion is True
    assert result.ready_for_release_dispatch is True
    assert result.execution_authorized is False
    assert result.release_publish_authorized is False
    assert len(result.evidence_digest) == 64


def test_release_target_version_is_exact() -> None:
    for version in ("9.0.0", "10.0.1", "10.0.0-rc.1", "v10.0.0", " 10.0.0 "):
        with pytest.raises(ProductionReleaseError, match="exactly 10.0.0"):
            evaluate_production_release(
                target_version=version,
                commit_sha="a" * 40,
                validation_gates=_gates(),
                release_artifacts=_artifacts(),
            )


def test_release_candidate_requires_exact_commit_identity() -> None:
    for sha in ("A" * 40, "a" * 39, "a" * 41, "not-a-sha", " a" * 20):
        with pytest.raises(ProductionReleaseError, match="commit SHA"):
            evaluate_production_release(
                target_version=EXPECTED_STABLE_VERSION,
                commit_sha=sha,
                validation_gates=_gates(),
                release_artifacts=_artifacts(),
            )


def test_missing_or_unexpected_gate_evidence_fails_closed() -> None:
    missing = _gates()
    missing.pop("batch_17_performance")
    with pytest.raises(ProductionReleaseError, match="exact governed set"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="b" * 40,
            validation_gates=missing,
            release_artifacts=_artifacts(),
        )

    unexpected = _gates() | {"candidate_supplied_gate": True}
    with pytest.raises(ProductionReleaseError, match="unexpected"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="b" * 40,
            validation_gates=unexpected,
            release_artifacts=_artifacts(),
        )


def test_failed_or_truthy_non_boolean_gate_evidence_fails_closed() -> None:
    failed = _gates()
    failed["security_gate_v2"] = False
    with pytest.raises(ProductionReleaseError, match="failed closed"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="c" * 40,
            validation_gates=failed,
            release_artifacts=_artifacts(),
        )

    truthy = _gates()
    truthy["ci"] = 1
    with pytest.raises(ProductionReleaseError, match="exact boolean"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="c" * 40,
            validation_gates=truthy,
            release_artifacts=_artifacts(),
        )


def test_release_artifact_contract_is_exact_and_complete() -> None:
    missing = _artifacts()
    missing.pop("sbom_spdx")
    with pytest.raises(ProductionReleaseError, match="release artifact"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="d" * 40,
            validation_gates=_gates(),
            release_artifacts=missing,
        )


def test_existing_release_target_is_immutable() -> None:
    with pytest.raises(ProductionReleaseError, match="already exists"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="e" * 40,
            validation_gates=_gates(),
            release_artifacts=_artifacts(),
            release_already_published=True,
        )


def test_release_already_published_requires_exact_boolean() -> None:
    with pytest.raises(ProductionReleaseError, match="exact boolean"):
        evaluate_production_release(
            target_version=EXPECTED_STABLE_VERSION,
            commit_sha="f" * 40,
            validation_gates=_gates(),
            release_artifacts=_artifacts(),
            release_already_published=0,  # type: ignore[arg-type]
        )


def test_evidence_digest_is_deterministic_and_commit_bound() -> None:
    first = evaluate_production_release(
        target_version=EXPECTED_STABLE_VERSION,
        commit_sha="1" * 40,
        validation_gates=_gates(),
        release_artifacts=_artifacts(),
    )
    second = evaluate_production_release(
        target_version=EXPECTED_STABLE_VERSION,
        commit_sha="1" * 40,
        validation_gates=dict(reversed(list(_gates().items()))),
        release_artifacts=dict(reversed(list(_artifacts().items()))),
    )
    other = evaluate_production_release(
        target_version=EXPECTED_STABLE_VERSION,
        commit_sha="2" * 40,
        validation_gates=_gates(),
        release_artifacts=_artifacts(),
    )

    assert first.evidence_digest == second.evidence_digest
    assert first.evidence_digest != other.evidence_digest
