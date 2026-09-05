from app.permission_engine import PermissionEngine, PermissionMode, RiskLevel
from app.tool_permission_runtime import ToolPermissionRuntime


def base_permissions(**overrides):
    values = {
        "allow_commands": True,
        "allow_web": True,
        "allow_images": True,
        "allow_browser": True,
        "allow_desktop": True,
        "allow_voice": True,
        "allow_connectors": True,
        "allow_mcp": True,
        "allow_self_improvement": True,
        "approval_mode": "standard",
    }
    values.update(overrides)
    return values


def test_disabled_legacy_gate_cannot_be_overridden_by_v9_rule():
    engine = PermissionEngine(PermissionMode.ALWAYS_ALLOW)
    engine.set_tool_rule("run_command", PermissionMode.ALWAYS_ALLOW, RiskLevel.EXECUTE)
    runtime = ToolPermissionRuntime(engine)

    result = runtime.authorize(
        tool_name="run_command",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(allow_commands=False),
        use_v9_policy=True,
    )

    assert result.allowed is False
    assert result.approval_required is False
    assert result.decision.source == "legacy_gate"


def test_legacy_standard_mode_preserves_approval_for_external_tools():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="connector_request",
        declared_risk="external",
        gate="connectors",
        permissions=base_permissions(),
    )

    assert result.allowed is False
    assert result.approval_required is True
    assert result.profile.network_effect is True
    assert result.profile.credential_effect is True


def test_legacy_safe_mode_blocks_command_execution():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="run_command",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(approval_mode="safe"),
    )

    assert result.allowed is False
    assert result.approval_required is False


def test_v9_default_requires_approval_when_no_explicit_rule_exists():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="run_command",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(),
        use_v9_policy=True,
    )

    assert result.allowed is False
    assert result.approval_required is True
    assert result.decision.mode == PermissionMode.ASK_EVERY_TIME
    assert result.decision.source == "default"


def test_v9_session_rule_requires_grant_then_allows():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("run_command", PermissionMode.ALLOW_SESSION, RiskLevel.EXECUTE)
    runtime = ToolPermissionRuntime(engine)

    before = runtime.authorize(
        tool_name="run_command",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(),
        use_v9_policy=True,
    )
    assert before.allowed is False
    assert before.approval_required is True

    engine.grant_session("run_command")
    after = runtime.authorize(
        tool_name="run_command",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(),
        use_v9_policy=True,
    )
    assert after.allowed is True
    assert after.approval_required is False


def test_unknown_legacy_gate_fails_closed():
    runtime = ToolPermissionRuntime()
    result = runtime.authorize(
        tool_name="mystery_tool",
        declared_risk="read",
        gate="unknown_gate",
        permissions=base_permissions(),
    )

    assert result.allowed is False
    assert result.approval_required is False


def test_host_sandbox_fallback_requires_explicit_approval_even_when_tool_is_allowed():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("run_python_sandbox", PermissionMode.ALWAYS_ALLOW, RiskLevel.EXECUTE)
    runtime = ToolPermissionRuntime(engine)

    result = runtime.authorize(
        tool_name="run_python_sandbox",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(),
        use_v9_policy=True,
        arguments={"code": "print('ok')", "use_host_fallback": True},
    )

    assert result.allowed is False
    assert result.approval_required is True
    assert result.decision.source == "sandbox_boundary"
    assert "not a security sandbox" in result.reason


def test_docker_sandbox_path_preserves_existing_permission_decision():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("run_python_sandbox", PermissionMode.ALWAYS_ALLOW, RiskLevel.EXECUTE)
    runtime = ToolPermissionRuntime(engine)

    result = runtime.authorize(
        tool_name="run_python_sandbox",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(),
        use_v9_policy=True,
        arguments={"code": "print('ok')", "use_host_fallback": False},
    )

    assert result.allowed is True
    assert result.approval_required is False
    assert result.decision.source == "tool"


def test_host_fallback_cannot_bypass_safe_mode_denial():
    runtime = ToolPermissionRuntime()

    result = runtime.authorize(
        tool_name="run_python_sandbox",
        declared_risk="execute",
        gate="commands",
        permissions=base_permissions(approval_mode="safe"),
        arguments={"code": "print('ok')", "use_host_fallback": True},
    )

    assert result.allowed is False
    assert result.approval_required is False
    assert result.decision.source == "legacy"
