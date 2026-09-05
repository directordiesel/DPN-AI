import pytest

from app.connector_governance_v9 import ConnectorGovernanceV9


def test_read_requires_discovery_and_allowlist():
    policy = ConnectorGovernanceV9()
    denied = policy.build_request("mcp", "read", "srv-1", "list_issues", discovered_actions=["list_issues"])
    assert denied["ok"] is False
    assert "action_not_allowlisted" in denied["failures"]

    allowed = policy.build_request(
        "mcp", "read", "srv-1", "list_issues",
        discovered_actions=["list_issues"], allowed_actions=["list_issues"],
    )
    assert allowed["ok"] is True
    assert allowed["approval_required"] is False


def test_write_requires_approval_and_idempotency():
    policy = ConnectorGovernanceV9()
    denied = policy.build_request(
        "connector", "write", "crm", "create_contact",
        discovered_actions=["create_contact"], allowed_actions=["create_contact"],
    )
    assert set(denied["failures"]) == {"approval_required", "idempotency_key_required"}

    allowed = policy.build_request(
        "connector", "write", "crm", "create_contact",
        discovered_actions=["create_contact"], allowed_actions=["create_contact"],
        approval_present=True, idempotency_key="contact-42",
    )
    assert allowed["ok"] is True
    assert allowed["risk"] == "external_write"


def test_delete_is_destructive_and_requires_approval_but_not_idempotency_key():
    policy = ConnectorGovernanceV9()
    result = policy.build_request(
        "mcp", "delete", "github-server", "delete_branch",
        discovered_actions=["delete_branch"], allowed_actions=["delete_branch"], approval_present=True,
    )
    assert result["ok"] is True
    assert result["risk"] == "destructive"
    assert result["approval_required"] is True


def test_rejects_unknown_system_operation_and_unsafe_fields():
    policy = ConnectorGovernanceV9()
    with pytest.raises(ValueError, match="system must"):
        policy.build_request("shell", "read", "x", "y")
    with pytest.raises(ValueError, match="operation must"):
        policy.build_request("mcp", "spawn", "x", "y")
    with pytest.raises(ValueError, match="target_id"):
        policy.build_request("mcp", "read", "bad\nserver", "tool")


def test_operation_cap_is_bounded():
    policy = ConnectorGovernanceV9()
    result = policy.build_request(
        "connector", "read", "api", "fetch",
        max_operations=9999, discovered_actions=["fetch"], allowed_actions=["fetch"],
    )
    assert result["max_operations"] == 200


def test_completion_for_write_requires_live_policy_approval_and_verification():
    missing = ConnectorGovernanceV9.evaluate_completion(
        {"discovery_complete": True, "allowlist_checked": True, "live_policy_revalidated": True},
        write_expected=True,
    )
    assert missing["ok"] is False
    assert "approval_evidence_missing" in missing["failures"]
    assert "write_verification_missing" in missing["failures"]

    complete = ConnectorGovernanceV9.evaluate_completion(
        {
            "discovery_complete": True,
            "allowlist_checked": True,
            "live_policy_revalidated": True,
            "approval_evidence": {"id": "approval-1"},
            "write_verified": True,
        },
        write_expected=True,
    )
    assert complete["completion_allowed"] is True


def test_plaintext_secret_or_unreconciled_partial_failure_blocks_completion():
    result = ConnectorGovernanceV9.evaluate_completion(
        {
            "discovery_complete": True,
            "allowlist_checked": True,
            "live_policy_revalidated": True,
            "plaintext_secret_detected": True,
            "partial_failure_unreconciled": True,
        }
    )
    assert result["ok"] is False
    assert "plaintext_secret_detected" in result["failures"]
    assert "partial_failure_unreconciled" in result["failures"]
