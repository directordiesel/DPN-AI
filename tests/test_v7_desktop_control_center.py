from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "desktop_control_center_v7.py"
spec = spec_from_file_location("desktop_control_center_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_default_desktop_contract_targets_windows_and_local_runtime():
    plan = module.build_desktop_control_center_plan("desktop")
    assert plan["native_shell_target"] == "windows"
    assert plan["execution_policy"]["require_local_runtime"] is True
    assert plan["execution_policy"]["native_shell_must_not_spawn_terminal_for_normal_use"] is True


def test_panels_are_validated_and_deduplicated():
    plan = module.build_desktop_control_center_plan("x", ["overview", "overview", "missions", "bad"])
    assert plan["panels"] == ["overview", "missions"]


def test_runtime_and_failure_state_must_not_be_faked_or_hidden():
    policy = module.build_desktop_control_center_plan("x")["execution_policy"]
    assert policy["never_fake_online_or_model_status"] is True
    assert policy["never_hide_failed_or_blocked_work"] is True


def test_protected_actions_are_never_auto_approved():
    assert module.build_desktop_control_center_plan("x")["execution_policy"]["never_auto_approve_protected_actions"] is True


def test_control_center_requires_recovery_and_evidence_visibility():
    plan = module.build_desktop_control_center_plan("x")
    ids = [stage["id"] for stage in plan["stages"]]
    assert "recovery" in ids
    assert "verify" in ids
    assert "mission_evidence_is_inspectable" in plan["quality_gates"]


def test_missing_runtime_state_blocks_completion():
    result = module.evaluate_control_center_state({"version": "7"})
    assert result["ok"] is False
    assert "runtime" in result["missing_state"]
    assert result["completion_allowed"] is False


def test_inconsistent_or_blocked_state_cannot_pass():
    base = {
        "runtime": {"ok": True}, "version": "7", "project_scope": "p",
        "mission_state": "idle", "approval_state": "clear", "verification_state": "verified"
    }
    inconsistent = dict(base, inconsistencies=["model shown online but backend offline"])
    blocked = dict(base, blocked=True)
    assert module.evaluate_control_center_state(inconsistent)["ok"] is False
    assert module.evaluate_control_center_state(blocked)["ok"] is False


def test_complete_consistent_state_can_pass():
    state = {
        "runtime": {"ok": True}, "version": "7", "project_scope": "p",
        "mission_state": "idle", "approval_state": "clear", "verification_state": "verified"
    }
    assert module.evaluate_control_center_state(state)["ok"] is True
