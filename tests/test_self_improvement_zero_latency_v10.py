from app.autonomous_coding_runtime_v10 import CodingMission, CodingStage, ValidationEvidence
from app.benchmark_laboratory_v10 import BenchmarkRun
from app.self_improvement_v10 import BenchmarkGatedSelfImprovement, SelfImprovementEvidenceStore


def test_zero_latency_baseline_with_nonzero_candidate_fails_with_finite_evidence(tmp_path):
    mission = CodingMission(
        mission_id="zero-latency",
        repository="directordiesel/DPN-AI",
        objective="Protect benchmark evidence serialization",
        stage=CodingStage.READY,
        review_passed=True,
        security_passed=True,
        ci_passed=True,
    )
    mission.record_validation(ValidationEvidence(name="pytest", passed=True))
    controller = BenchmarkGatedSelfImprovement(SelfImprovementEvidenceStore(tmp_path / "evidence.json"))

    baseline = BenchmarkRun(
        model_name="dpn-self-improvement-candidate-v10",
        task_family="coding",
        task_id="baseline",
        passed=True,
        quality_score=1.0,
        latency_ms=0,
    )
    candidate = BenchmarkRun(
        model_name="dpn-self-improvement-candidate-v10",
        task_family="coding",
        task_id="candidate",
        passed=True,
        quality_score=1.0,
        latency_ms=1,
    )

    evaluation = controller.evaluate(
        candidate_id="candidate-zero-latency",
        mission=mission,
        benchmark_model_name="dpn-self-improvement-candidate-v10",
        required_task_families=["coding"],
        baseline_runs=[baseline],
        candidate_runs=[candidate],
    )

    assert evaluation.gate_passed is False
    assert evaluation.families[0].latency_ratio < 100
    assert evaluation.families[0].failures == ("latency_regression",)
    assert (tmp_path / "evidence.json").read_text(encoding="utf-8").find("Infinity") == -1
