from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "security_qa_v7.py"
spec = spec_from_file_location("security_qa_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_default_plan_covers_release_and_security_surfaces():
    plan = module.build_security_qa_plan("harden v7")
    assert "versioning" in plan["domains"]
    assert "auth" in plan["domains"]
    assert "recovery" in plan["domains"]
    assert plan["execution_policy"]["require_release_consistency"] is True


def test_no_test_or_security_weakening_is_allowed():
    policy = module.build_security_qa_plan("x")["execution_policy"]
    assert policy["never_weaken_tests_to_pass"] is True
    assert policy["never_disable_security_controls_to_pass"] is True
    assert policy["fail_closed_on_unknown_authorization"] is True


def test_domains_deduplicate_and_findings_are_bounded():
    plan = module.build_security_qa_plan("x", ["auth", "auth", "desktop", "bad"], max_findings=9999)
    assert plan["domains"] == ["auth", "desktop"]
    assert plan["limits"]["max_findings"] == 500


def test_version_consistency_is_a_quality_gate():
    plan = module.build_security_qa_plan("x")
    assert "version_metadata_consistent" in plan["quality_gates"]
    assert plan["execution_policy"]["version_source_of_truth_must_be_single_and_consistent"] is True


def test_missing_evidence_blocks_completion():
    result = module.evaluate_security_qa_evidence({"dependency_audit": True})
    assert result["ok"] is False
    assert "secret_scan" in result["missing_evidence"]
    assert result["completion_allowed"] is False


def test_unresolved_high_finding_blocks_release():
    evidence = {
        "dependency_audit": True, "secret_scan": True, "auth_tests": True,
        "negative_tests": True, "runtime_tests": True, "version_check": True,
        "test_results": True, "security_results": True,
        "findings": [{"severity": "high", "title": "auth bypass", "resolved": False}],
    }
    result = module.evaluate_security_qa_evidence(evidence)
    assert result["ok"] is False
    assert len(result["release_blockers"]) == 1


def test_resolved_high_finding_does_not_block_completion():
    evidence = {
        "dependency_audit": True, "secret_scan": True, "auth_tests": True,
        "negative_tests": True, "runtime_tests": True, "version_check": True,
        "test_results": True, "security_results": True,
        "findings": [{"severity": "high", "title": "fixed", "resolved": True}],
    }
    assert module.evaluate_security_qa_evidence(evidence)["ok"] is True


def test_weakened_controls_always_block_completion():
    evidence = {
        "dependency_audit": True, "secret_scan": True, "auth_tests": True,
        "negative_tests": True, "runtime_tests": True, "version_check": True,
        "test_results": True, "security_results": True, "tests_weakened": True,
    }
    result = module.evaluate_security_qa_evidence(evidence)
    assert result["ok"] is False
    assert result["tests_or_controls_weakened"] is True
