from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "connector_orchestration_v6.py"
spec = spec_from_file_location("connector_orchestration_v6", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_defaults_to_http_and_mcp_with_live_authorization():
    plan = module.build_connector_orchestration_plan("sync records")
    assert plan["systems"] == ["http", "mcp"]
    assert plan["execution_policy"]["persisted_configuration_is_not_authorization"] is True
    assert plan["execution_policy"]["recheck_live_policy_before_each_protected_action"] is True


def test_aliases_and_duplicate_systems_normalize():
    plan = module.build_connector_orchestration_plan("work", systems=["REST", "api", "git", "repo", "sql"])
    assert plan["systems"] == ["api", "github", "database"]


def test_external_actions_are_disabled_by_default():
    plan = module.build_connector_orchestration_plan("write remote data")
    assert plan["execution_policy"]["external_actions_allowed"] is False
    assert plan["execution_policy"]["writes_require_approval"] is True


def test_operation_limit_is_bounded():
    assert module.build_connector_orchestration_plan("x", max_operations=0)["limits"]["max_operations"] == 1
    assert module.build_connector_orchestration_plan("x", max_operations=1000)["limits"]["max_operations"] == 200


def test_mcp_safety_and_secret_policy_are_explicit():
    policy = module.build_connector_orchestration_plan("mcp task", systems=["mcp"])["execution_policy"]
    assert policy["mcp_tools_must_be_discovered_before_allowlisting"] is True
    assert policy["mcp_calls_must_be_allowlisted"] is True
    assert policy["secret_values_must_use_vault_references"] is True
    assert policy["never_log_plaintext_secrets"] is True


def test_http_host_escape_and_redirect_safety_are_explicit():
    policy = module.build_connector_orchestration_plan("api task", systems=["http"])["execution_policy"]
    assert policy["http_connectors_must_remain_host_and_method_bounded"] is True
    assert policy["redirect_or_host_escape_must_not_be_followed"] is True


def test_sync_requires_idempotency_and_partial_failure_reconciliation():
    plan = module.build_connector_orchestration_plan("sync", mode="sync")
    assert plan["execution_policy"]["idempotency_required"] is True
    assert plan["execution_policy"]["no_silent_cross_system_partial_success"] is True
    assert "partial_failure_reconciled" in plan["quality_gates"]


def test_monitor_adds_baseline_without_claiming_scheduler():
    plan = module.build_connector_orchestration_plan("watch upstream", mode="monitor")
    ids = [stage["id"] for stage in plan["stages"]]
    assert "baseline" in ids
    assert "execute" in ids


def test_migrate_adds_mapping_and_readback_evidence():
    plan = module.build_connector_orchestration_plan("move records", mode="migrate")
    ids = [stage["id"] for stage in plan["stages"]]
    assert "migration_map" in ids
    assert plan["execution_policy"]["write_success_requires_readback_or_equivalent_evidence"] is True


def test_invalid_mode_and_system_fall_back_safely():
    plan = module.build_connector_orchestration_plan("x", systems=["unknown"], mode="nonsense")
    assert plan["mode"] == "plan"
    assert plan["systems"] == ["http"]
