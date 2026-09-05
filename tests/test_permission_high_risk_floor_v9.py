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


def test_persistent_rule_cannot_permanently_allow_destructive_action():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("delete_path", PermissionMode.ALWAYS_ALLOW, RiskLevel.DESTRUCTIVE)

    decision = engine.evaluate("delete_path", RiskLevel.DESTRUCTIVE)

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.mode == PermissionMode.ASK_EVERY_TIME
    assert decision.source == "high_risk_floor"
    assert "fresh human approval" in decision.reason


def test_session_grant_cannot_bypass_destructive_action_floor():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("delete_path", PermissionMode.ALLOW_SESSION, RiskLevel.DESTRUCTIVE)
    engine.grant_session("delete_path")

    decision = engine.evaluate("delete_path", RiskLevel.DESTRUCTIVE)

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.source == "high_risk_floor"


def test_persistent_rule_cannot_permanently_allow_desktop_control():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("desktop_automation", PermissionMode.ALWAYS_ALLOW, RiskLevel.DESKTOP)

    decision = engine.evaluate("desktop_automation", RiskLevel.DESKTOP)

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.source == "high_risk_floor"


def test_lower_risk_persistent_rule_behavior_is_preserved():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("run_command", PermissionMode.ALWAYS_ALLOW, RiskLevel.EXECUTE)

    decision = engine.evaluate("run_command", RiskLevel.EXECUTE)

    assert decision.allowed is True
    assert decision.approval_required is False
    assert decision.mode == PermissionMode.ALWAYS_ALLOW
    assert decision.source == "tool"


def test_legacy_gate_still_blocks_before_high_risk_floor():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("desktop_automation", PermissionMode.ALWAYS_ALLOW, RiskLevel.DESKTOP)
    runtime = ToolPermissionRuntime(engine)

    result = runtime.authorize(
        tool_name="desktop_automation",
        declared_risk="desktop",
        gate="desktop",
        permissions=base_permissions(allow_desktop=False),
        use_v9_policy=True,
    )

    assert result.allowed is False
    assert result.approval_required is False
    assert result.decision.source == "legacy_gate"


def test_desktop_runtime_surfaces_high_risk_floor_when_gate_is_enabled():
    engine = PermissionEngine(PermissionMode.ASK_EVERY_TIME)
    engine.set_tool_rule("desktop_automation", PermissionMode.ALWAYS_ALLOW, RiskLevel.DESKTOP)
    runtime = ToolPermissionRuntime(engine)

    result = runtime.authorize(
        tool_name="desktop_automation",
        declared_risk="desktop",
        gate="desktop",
        permissions=base_permissions(),
        use_v9_policy=True,
    )

    assert result.allowed is False
    assert result.approval_required is True
    assert result.decision.source == "high_risk_floor"
