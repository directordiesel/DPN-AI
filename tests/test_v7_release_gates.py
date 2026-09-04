from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "release_gates_v7.py"
spec = spec_from_file_location("release_gates_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def _passing_evidence():
    return {
        "gates": {gate: "pass" for gate in module.REQUIRED_GATES},
        "blockers": [],
        "critical_or_high_findings": [],
        "tests_weakened": False,
        "security_controls_weakened": False,
        "evidence_matches_candidate_head": True,
    }


def test_unknown_gate_blocks_release():
    evidence = _passing_evidence()
    evidence["gates"].pop("security_gate")
    result = module.evaluate_release_candidate(evidence)
    assert result["release_ready"] is False
    assert "security_gate" in result["missing_gates"]


def test_failed_gate_blocks_release():
    evidence = _passing_evidence()
    evidence["gates"]["unit_tests"] = "fail"
    result = module.evaluate_release_candidate(evidence)
    assert result["release_ready"] is False
    assert "unit_tests" in result["failed_gates"]


def test_stale_evidence_blocks_release():
    evidence = _passing_evidence()
    evidence["evidence_matches_candidate_head"] = False
    assert module.evaluate_release_candidate(evidence)["release_ready"] is False


def test_security_or_test_weakening_blocks_release():
    evidence = _passing_evidence()
    evidence["tests_weakened"] = True
    assert module.evaluate_release_candidate(evidence)["release_ready"] is False
    evidence = _passing_evidence()
    evidence["security_controls_weakened"] = True
    assert module.evaluate_release_candidate(evidence)["release_ready"] is False


def test_high_findings_block_release():
    evidence = _passing_evidence()
    evidence["critical_or_high_findings"] = ["example"]
    assert module.evaluate_release_candidate(evidence)["release_ready"] is False


def test_all_gates_for_exact_head_allow_release():
    result = module.evaluate_release_candidate(_passing_evidence())
    assert result["release_ready"] is True
    assert result["merge_allowed_by_gates"] is True
