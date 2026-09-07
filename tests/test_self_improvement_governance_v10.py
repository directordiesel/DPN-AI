from pathlib import Path

import pytest

from app.self_improvement_governance_v10 import CandidateCodeBinding, ExecutedBenchmarkManifest, GovernedSelfImprovement
from app.self_improvement_v10 import SelfImprovementError, SelfImprovementEvaluation, SelfImprovementEvidenceStore


def _evaluation(store: SelfImprovementEvidenceStore) -> SelfImprovementEvaluation:
    evaluation = SelfImprovementEvaluation(
        schema_version=1,
        candidate_id="candidate-1",
        candidate_digest="a" * 64,
        benchmark_model_name="model-a",
        mission_id="mission-1",
        repository="directordiesel/DPN-AI",
        objective="improve runtime",
        required_families=("coding", "security"),
        families=(),
        gate_passed=True,
        reason="passed",
    )
    store.record(evaluation)
    return evaluation


def _manifest(commit: str = "b" * 40) -> ExecutedBenchmarkManifest:
    return ExecutedBenchmarkManifest(
        manifest_id="manifest-1",
        benchmark_model_name="model-a",
        candidate_commit_sha=commit,
        required_families=("coding", "security"),
        run_ids=("run-1", "run-2"),
        result_digest_sha256="c" * 64,
        executor_identity="dpn-ci",
    )


def _binding(commit: str = "b" * 40) -> CandidateCodeBinding:
    return CandidateCodeBinding(
        repository="directordiesel/DPN-AI",
        candidate_commit_sha=commit,
        changed_paths=("app/example.py", "tests/test_example.py"),
        tree_digest_sha256="d" * 64,
    )


def test_application_request_is_approval_only_and_exactly_commit_bound(tmp_path: Path) -> None:
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    evaluation = _evaluation(store)
    request = GovernedSelfImprovement(store).request_application(
        evaluation=evaluation,
        manifest=_manifest(),
        code_binding=_binding(),
    )
    assert request.candidate_commit_sha == "b" * 40
    assert request.approval_required is True
    assert request.execution_authorized is False
    assert request.required_authority == "explicit_human_approval"


def test_application_rejects_commit_mismatch(tmp_path: Path) -> None:
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    evaluation = _evaluation(store)
    with pytest.raises(SelfImprovementError, match="different candidate commits"):
        GovernedSelfImprovement(store).request_application(
            evaluation=evaluation,
            manifest=_manifest("b" * 40),
            code_binding=_binding("e" * 40),
        )


def test_application_rejects_wrong_model_or_family_manifest(tmp_path: Path) -> None:
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    evaluation = _evaluation(store)
    bad = ExecutedBenchmarkManifest(
        manifest_id="manifest-1",
        benchmark_model_name="other-model",
        candidate_commit_sha="b" * 40,
        required_families=("coding", "security"),
        run_ids=("run-1",),
        result_digest_sha256="c" * 64,
        executor_identity="dpn-ci",
    )
    with pytest.raises(SelfImprovementError, match="model"):
        GovernedSelfImprovement(store).request_application(evaluation=evaluation, manifest=bad, code_binding=_binding())


def test_application_requires_durable_evaluation(tmp_path: Path) -> None:
    store = SelfImprovementEvidenceStore(tmp_path / "evidence.json")
    evaluation = SelfImprovementEvaluation(
        schema_version=1,
        candidate_id="candidate-1",
        candidate_digest="a" * 64,
        benchmark_model_name="model-a",
        mission_id="mission-1",
        repository="directordiesel/DPN-AI",
        objective="improve runtime",
        required_families=("coding", "security"),
        families=(),
        gate_passed=True,
        reason="passed",
    )
    with pytest.raises(SelfImprovementError, match="durable"):
        GovernedSelfImprovement(store).request_application(evaluation=evaluation, manifest=_manifest(), code_binding=_binding())


def test_code_binding_rejects_repository_escape() -> None:
    with pytest.raises(SelfImprovementError, match="escapes"):
        CandidateCodeBinding("repo", "b" * 40, ("../secret",), "d" * 64).normalized()


def test_rollback_is_approval_only() -> None:
    request = GovernedSelfImprovement.request_rollback(
        candidate_digest="a" * 64,
        deployed_commit_sha="b" * 40,
        rollback_target_sha="c" * 40,
        reason="regression detected",
    )
    assert request.approval_required is True
    assert request.execution_authorized is False
    assert request.deployed_commit_sha != request.rollback_target_sha


def test_rollback_rejects_same_commit() -> None:
    with pytest.raises(SelfImprovementError, match="must differ"):
        GovernedSelfImprovement.request_rollback(
            candidate_digest="a" * 64,
            deployed_commit_sha="b" * 40,
            rollback_target_sha="b" * 40,
            reason="bad",
        )
