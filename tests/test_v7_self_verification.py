from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "self_verification_v7.py"
spec = spec_from_file_location("self_verification_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_code_verification_requires_tests_security_and_runtime_evidence():
    plan = module.build_self_verification_plan("verify code", artifact_type="code")
    assert "targeted_tests" in plan["validators"]
    assert "security_checks" in plan["validators"]
    assert "runtime_or_build_evidence" in plan["validators"]


def test_repair_budget_is_bounded():
    assert module.build_self_verification_plan("x", max_repair_attempts=-1)["limits"]["max_repair_attempts"] == 0
    assert module.build_self_verification_plan("x", max_repair_attempts=99)["limits"]["max_repair_attempts"] == 4


def test_policy_forbids_test_weakening_and_security_bypass():
    policy = module.build_self_verification_plan("x")["execution_policy"]
    assert policy["tests_must_not_be_weakened_to_pass"] is True
    assert policy["security_controls_must_not_be_disabled"] is True
    assert policy["acceptance_criteria_must_not_be_relaxed_after_failure"] is True


def test_missing_criteria_or_checks_blocks_completion():
    result = module.evaluate_verification_evidence({})
    assert result["ok"] is False
    assert "criteria" in result["missing_evidence"]
    assert "checks" in result["missing_evidence"]


def test_failed_check_blocks_completion():
    result = module.evaluate_verification_evidence({
        "criteria": ["tests pass"],
        "checks": [{"name": "tests", "status": "failed", "evidence": "pytest failure"}],
    })
    assert result["completion_allowed"] is False
    assert result["policy"]["failed_check_blocks_completion"] is True


def test_unsupported_check_blocks_completion():
    result = module.evaluate_verification_evidence({
        "criteria": ["artifact exists"],
        "checks": [{"name": "artifact", "status": "pass", "evidence": ""}],
    })
    assert result["completion_allowed"] is False
    assert result["policy"]["unsupported_check_blocks_completion"] is True


def test_unresolved_items_prevent_full_success():
    result = module.evaluate_verification_evidence({
        "criteria": ["all good"],
        "checks": [{"name": "one", "status": "pass", "evidence": "verified"}],
        "unresolved": ["one warning"],
    })
    assert result["status"] == "partial"
    assert result["completion_allowed"] is False


def test_supported_passing_checks_allow_completion():
    result = module.evaluate_verification_evidence({
        "criteria": ["all good"],
        "checks": [{"name": "one", "status": "pass", "evidence": "verified"}],
    })
    assert result["ok"] is True
    assert result["status"] == "pass"
    assert result["completion_allowed"] is True


def test_unknown_artifact_type_falls_back_safely():
    plan = module.build_self_verification_plan("x", artifact_type="nonsense")
    assert plan["artifact_type"] == "generic"
