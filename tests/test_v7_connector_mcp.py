from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "connector_mcp_v7.py"
spec = spec_from_file_location("connector_mcp_v7", MODULE_PATH)
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_defaults_are_read_safe():
    plan = module.build_connector_mcp_v7_plan("inspect connectors")
    policy = plan["execution_policy"]
    assert policy["external_actions_allowed"] is False
    assert policy["writes_require_approval"] is True
    assert policy["never_log_plaintext_secrets"] is True
    assert policy["persisted_configuration_is_not_authorization"] is True


def test_aliases_normalize_and_deduplicate():
    plan = module.build_connector_mcp_v7_plan("x", systems=["rest", "graphql", "repo", "git", "model-context-protocol", "sql", "drive"])
    assert plan["systems"] == ["api", "github", "mcp", "database", "storage"]


def test_operation_limit_is_bounded():
    assert module.build_connector_mcp_v7_plan("x", max_operations=0)["limits"]["max_operations"] == 1
    assert module.build_connector_mcp_v7_plan("x", max_operations=999)["limits"]["max_operations"] == 200


def test_migrate_mode_adds_mapping_stage():
    plan = module.build_connector_mcp_v7_plan("migrate", mode="migrate")
    assert "migration_map" in [stage["id"] for stage in plan["stages"]]


def test_monitor_mode_requires_scheduler_evidence():
    plan = module.build_connector_mcp_v7_plan("monitor", mode="monitor")
    assert "baseline" in [stage["id"] for stage in plan["stages"]]
    assert plan["execution_policy"]["monitoring_requires_scheduler_evidence"] is True


def test_ambiguous_targets_are_blocked_before_write():
    policy = module.build_connector_mcp_v7_plan("write")["execution_policy"]
    assert policy["ambiguous_external_targets_require_resolution_before_write"] is True


def test_evaluator_accepts_verified_write():
    result = module.evaluate_connector_evidence_v7({
        "discovery_complete": True,
        "authorization_checked": True,
        "operations": [{
            "system": "github", "tool": "update_file", "status": "success", "write": True,
            "verified": True, "approval_required": True, "approval_evidence": "approved"
        }],
    }, writes_expected=True)
    assert result["ok"] is True
    assert result["completion_allowed"] is True


def test_evaluator_rejects_unverified_write():
    result = module.evaluate_connector_evidence_v7({
        "discovery_complete": True,
        "authorization_checked": True,
        "operations": [{"system": "api", "tool": "write", "status": "success", "write": True, "verified": False}],
    }, writes_expected=True)
    assert "write_readback_verification_missing" in result["failures"]


def test_evaluator_rejects_missing_approval_evidence():
    result = module.evaluate_connector_evidence_v7({
        "discovery_complete": True,
        "authorization_checked": True,
        "operations": [{
            "system": "api", "tool": "write", "status": "success", "write": True,
            "verified": True, "approval_required": True
        }],
    }, writes_expected=True)
    assert "write_approval_evidence_missing" in result["failures"]


def test_evaluator_rejects_secrets_ambiguity_and_partial_failure():
    result = module.evaluate_connector_evidence_v7({
        "discovery_complete": True,
        "authorization_checked": True,
        "plaintext_secret_detected": True,
        "ambiguous_target_detected": True,
        "partial_failure_unreconciled": True,
    })
    assert "plaintext_secret_detected" in result["failures"]
    assert "ambiguous_target_detected" in result["failures"]
    assert "partial_failure_unreconciled" in result["failures"]


def test_incomplete_pagination_must_be_disclosed():
    result = module.evaluate_connector_evidence_v7({
        "discovery_complete": True,
        "authorization_checked": True,
        "pagination_incomplete": True,
    })
    assert "pagination_incomplete_undisclosed" in result["failures"]
