from __future__ import annotations

import json

import pytest

from app.autonomous_coding_runtime_v10 import CodingMission, CodingStage, ValidationEvidence
from app.benchmark_laboratory_v10 import BenchmarkRun
from app.self_improvement_v10 import (
    BenchmarkGatedSelfImprovement,
    SelfImprovementError,
    SelfImprovementEvidenceStore,
    SelfImprovementPolicy,
)


def _ready_mission() -> CodingMission:
    mission = CodingMission(
        mission_id="improvement-1",
        repository="directordiesel/DPN-AI",
        objective="Improve deterministic benchmark routing",
        stage=CodingStage.READY,
        affected_files=["app/example.py"],
        affected_tests=["tests/test_example.py"],
        review_passed=True,
        security_passed=True,
        ci_passed=True,
    )
    mission.record_validation(ValidationEvidence(name="pytest", passed=True, detail="all tests passed"))
    assert mission.ready is True
    return mission


def _run(family: str, *, success: bool = True, quality: float = 1.0, latency: int = 100) -> BenchmarkRun:
    return BenchmarkRun(
        model_name="dpn-self-improvement-candidate-v10",
        task_family=family,
        task_id=f"{family}-case",
        passed=success,
        quality_score=quality,
        latency_ms=latency,
    )


def test_candidate_requires_fully_ready_coding_mission(tmp_path):
    controller = BenchmarkGatedSelfImprovement(SelfImprovementEvidenceStore(tmp_path / "evidence.json"))
    mission = _ready_mission()
    mission.stage = CodingStage.CI

    with pytest.raises(SelfImprovementError, match="fully READY"):
        controller.evaluate(
            candidate_id="candidate-1",
            mission=mission,
            benchmark_model_name="dpn-self-improvement-candidate-v10",
            required_task_families=["coding"],
            baseline_runs=[_run("coding")],
            candidate_runs=[_run("coding")],
        )


def test_candidate_passes_only_with_complete_non_regressing_benchmark_evidence(tmp_path):
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    controller = BenchmarkGatedSelfImprovement(store)
    evaluation = controller.evaluate(
        candidate_id="candidate-1",
        mission=_ready_mission(),
        benchmark_model_name="dpn-self-improvement-candidate-v10",
        required_task_families=["coding", "security"],
        baseline_runs=[_run("coding", latency=120), _run("security", latency=120)],
        candidate_runs=[_run("coding", latency=110), _run("security", latency=115)],
    )

    assert evaluation.gate_passed is True
    assert evaluation.approval_required is True
    assert evaluation.execution_authorized is False
    assert all(item.passed for item in evaluation.families)
    assert store.get(evaluation.candidate_digest) == evaluation.to_dict()

    request = controller.request_promotion(evaluation)
    assert request.approval_required is True
    assert request.execution_authorized is False
    assert request.required_authority == "explicit_human_approval"


def test_success_or_quality_regression_fails_closed(tmp_path):
    controller = BenchmarkGatedSelfImprovement(
        SelfImprovementEvidenceStore(tmp_path / "evidence.json"),
        policy=SelfImprovementPolicy(minimum_success_rate=0.0, minimum_quality_score=0.0),
    )
    evaluation = controller.evaluate(
        candidate_id="candidate-regressed",
        mission=_ready_mission(),
        benchmark_model_name="dpn-self-improvement-candidate-v10",
        required_task_families=["coding"],
        baseline_runs=[_run("coding", quality=1.0)],
        candidate_runs=[_run("coding", success=False, quality=0.8)],
    )

    assert evaluation.gate_passed is False
    assert "success_regression" in evaluation.families[0].failures
    assert "quality_regression" in evaluation.families[0].failures
    with pytest.raises(SelfImprovementError, match="cannot request promotion"):
        controller.request_promotion(evaluation)


def test_latency_regression_is_bounded(tmp_path):
    controller = BenchmarkGatedSelfImprovement(
        SelfImprovementEvidenceStore(tmp_path / "evidence.json"),
        policy=SelfImprovementPolicy(max_latency_regression_ratio=0.10),
    )
    evaluation = controller.evaluate(
        candidate_id="candidate-slow",
        mission=_ready_mission(),
        benchmark_model_name="dpn-self-improvement-candidate-v10",
        required_task_families=["coding"],
        baseline_runs=[_run("coding", latency=100)],
        candidate_runs=[_run("coding", latency=112)],
    )
    assert evaluation.gate_passed is False
    assert evaluation.families[0].failures == ("latency_regression",)


def test_missing_required_family_fails_before_receipt(tmp_path):
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    controller = BenchmarkGatedSelfImprovement(store)
    with pytest.raises(SelfImprovementError, match="missing baseline or candidate"):
        controller.evaluate(
            candidate_id="candidate-incomplete",
            mission=_ready_mission(),
            benchmark_model_name="dpn-self-improvement-candidate-v10",
            required_task_families=["coding", "security"],
            baseline_runs=[_run("coding"), _run("security")],
            candidate_runs=[_run("coding")],
        )
    assert not (tmp_path / "evidence.json").exists()


def test_corrupt_evidence_store_fails_closed(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("not-json", encoding="utf-8")
    store = SelfImprovementEvidenceStore(path)
    with pytest.raises(SelfImprovementError, match="corrupt"):
        store.get("anything")


def test_candidate_digest_is_immutable_and_replay_is_idempotent(tmp_path):
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    controller = BenchmarkGatedSelfImprovement(store)
    kwargs = dict(
        candidate_id="candidate-stable",
        mission=_ready_mission(),
        benchmark_model_name="dpn-self-improvement-candidate-v10",
        required_task_families=["coding"],
        baseline_runs=[_run("coding", latency=100)],
        candidate_runs=[_run("coding", latency=100)],
    )
    first = controller.evaluate(**kwargs)
    second = controller.evaluate(**kwargs)
    assert first.candidate_digest == second.candidate_digest

    payload = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert list(payload["evaluations"]) == [first.candidate_digest]


def test_promotion_rejects_unstored_or_tampered_evaluation(tmp_path):
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    controller = BenchmarkGatedSelfImprovement(store)
    evaluation = controller.evaluate(
        candidate_id="candidate-1",
        mission=_ready_mission(),
        benchmark_model_name="dpn-self-improvement-candidate-v10",
        required_task_families=["coding"],
        baseline_runs=[_run("coding")],
        candidate_runs=[_run("coding")],
    )
    (tmp_path / "evidence.json").write_text('{"schema_version":1,"evaluations":{}}', encoding="utf-8")
    with pytest.raises(SelfImprovementError, match="exact durable"):
        controller.request_promotion(evaluation)
