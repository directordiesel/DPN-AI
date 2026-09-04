from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "capability_dashboard_release_v6.py"
spec = spec_from_file_location("capability_dashboard_release_v6", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_default_dashboard_covers_all_domains():
    plan = module.build_capability_dashboard_plan()
    assert plan["domains"] == module.CAPABILITY_DOMAINS
    assert "release_gate_evidence_attached" in plan["quality_gates"]


def test_dashboard_keeps_degraded_and_missing_capabilities_visible():
    policy = module.build_capability_dashboard_plan()["execution_policy"]
    assert policy["include_degraded_capabilities"] is True
    assert policy["do_not_hide_missing_optional_dependencies"] is True
    assert policy["do_not_treat_configured_as_healthy"] is True


def test_pending_or_failed_checks_cannot_mark_ready():
    policy = module.build_capability_dashboard_plan()["execution_policy"]
    assert policy["do_not_mark_ready_with_pending_checks"] is True
    assert policy["do_not_mark_ready_with_failed_checks"] is True


def test_release_gate_evaluator_requires_every_gate_by_default():
    gates = {name: True for name in module.RELEASE_GATES}
    gates["ci_success"] = False
    result = module.evaluate_release_gates(gates)
    assert result["ready"] is False
    assert result["missing"] == ["ci_success"]


def test_absent_release_gates_do_not_count_as_pass():
    result = module.evaluate_release_gates({"ci_success": True})
    assert result["ready"] is False
    assert "security_gate_success" in result["missing"]
    assert result["policy"]["no_pending_or_unknown_gate_counts_as_pass"] is True


def test_all_release_gates_can_pass():
    result = module.evaluate_release_gates({name: True for name in module.RELEASE_GATES})
    assert result["ready"] is True
    assert result["missing"] == []


def test_release_never_auto_merges_and_keeps_main_unchanged():
    policy = module.build_capability_dashboard_plan()["execution_policy"]
    assert policy["merge_requires_explicit_user_authorization"] is True
    assert policy["main_must_remain_unchanged_until_merge"] is True
    assert policy["pr_must_remain_draft_until_release_ready"] is True


def test_release_cannot_weaken_security_or_tests():
    policy = module.build_capability_dashboard_plan()["execution_policy"]
    assert policy["security_controls_must_not_be_weakened_for_release"] is True
    assert policy["tests_must_not_be_deleted_or_relaxed_to_force_green"] is True


def test_finding_limit_is_bounded():
    assert module.build_capability_dashboard_plan(max_findings=0)["limits"]["max_findings"] == 1
    assert module.build_capability_dashboard_plan(max_findings=9999)["limits"]["max_findings"] == 500


def test_unknown_domains_fall_back_to_complete_dashboard():
    plan = module.build_capability_dashboard_plan(domains=["unknown"])
    assert plan["domains"] == module.CAPABILITY_DOMAINS
