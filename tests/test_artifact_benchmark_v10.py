from app.artifact_benchmark_v10 import (
    ARTIFACT_REQUIRED_FAMILIES,
    ArtifactBenchmarkObservation,
    artifact_runs,
    evaluate_artifact_readiness,
)


def _passing_observations():
    return [
        ArtifactBenchmarkObservation(
            task_family=family,
            task_id=f"{family}:acceptance",
            passed=True,
            quality_score=1.0,
            latency_ms=1,
        )
        for family in ARTIFACT_REQUIRED_FAMILIES
    ]


def test_artifact_readiness_requires_all_four_professional_formats():
    readiness = evaluate_artifact_readiness(artifact_runs(_passing_observations()))
    assert readiness.ready is True
    assert readiness.passing_profiles == 4
    assert readiness.failing_profiles == ()


def test_artifact_readiness_fails_closed_when_one_format_is_missing():
    observations = _passing_observations()[:-1]
    readiness = evaluate_artifact_readiness(artifact_runs(observations))
    assert readiness.ready is False
    assert any(item.startswith("artifact_xlsx_professional:missing") or item.startswith("artifact_pptx_professional:missing") for item in readiness.failing_profiles)


def test_artifact_readiness_rejects_any_format_quality_regression():
    observations = _passing_observations()
    observations[0] = ArtifactBenchmarkObservation(
        task_family=observations[0].task_family,
        task_id=observations[0].task_id,
        passed=True,
        quality_score=0.99,
        latency_ms=1,
    )
    readiness = evaluate_artifact_readiness(artifact_runs(observations))
    assert readiness.ready is False
    assert any("quality_score" in item for item in readiness.failing_profiles)


def test_artifact_benchmark_rejects_unknown_family():
    observation = ArtifactBenchmarkObservation(
        task_family="artifact_unknown",
        task_id="unknown",
        passed=True,
        quality_score=1.0,
    )
    try:
        observation.to_run()
    except ValueError:
        pass
    else:
        raise AssertionError("unknown artifact benchmark family must fail closed")
