from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "automation_operations_studio.py"
spec = importlib.util.spec_from_file_location("automation_operations_studio", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_defaults_preserve_live_permission_model():
    plan = module.build_automation_operations_plan("Run store opening checks")
    policy = plan["execution_policy"]
    assert plan["mode"] == "operations"
    assert plan["trigger_type"] == "manual"
    assert policy["persisted_payloads_are_not_authorization"] is True
    assert policy["live_permission_check_before_every_external_action"] is True
    assert policy["external_actions_require_approval"] is True


def test_limits_are_bounded():
    plan = module.build_automation_operations_plan("Large workflow", max_steps=9999, max_retries=99)
    assert plan["limits"]["max_steps"] == 100
    assert plan["limits"]["max_retries"] == 5


def test_invalid_options_fall_back_safely():
    plan = module.build_automation_operations_plan("Fallback", mode="unknown", trigger_type="magic")
    assert plan["mode"] == "operations"
    assert plan["trigger_type"] == "manual"


def test_requested_steps_are_capped():
    steps = [{"id": str(index)} for index in range(200)]
    plan = module.build_automation_operations_plan("Bounded graph", steps=steps, max_steps=7)
    assert len(plan["requested_steps"]) == 7


def test_shutdown_and_cancellation_semantics_are_distinct():
    plan = module.build_automation_operations_plan("Recover")
    policy = plan["execution_policy"]
    assert policy["application_shutdown_is_pause_not_success"] is True
    assert policy["operator_cancellation_must_be_preserved"] is True
    assert policy["resume_from_verified_checkpoint"] is True


def test_retry_policy_is_evidence_driven():
    plan = module.build_automation_operations_plan("Retry")
    policy = plan["execution_policy"]
    assert policy["retry_only_observed_transient_failures"] is True
    assert policy["do_not_retry_permission_or_validation_failures_blindly"] is True
    assert "approval_required" in plan["failure_classes"]["blocked"]
    assert "timeout" in plan["failure_classes"]["transient"]


def test_quality_gates_require_audit_and_completion_evidence():
    plan = module.build_automation_operations_plan("Audit")
    assert "live_permissions_checked" in plan["quality_gates"]
    assert "step_outputs_recorded" in plan["quality_gates"]
    assert "completion_evidence_present" in plan["quality_gates"]
