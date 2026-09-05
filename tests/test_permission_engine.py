from app.permission_engine import PermissionEngine, PermissionMode, RiskLevel


def test_default_policy_fails_closed_with_approval():
    decision = PermissionEngine().evaluate("read_file", RiskLevel.READ)
    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.mode == PermissionMode.ASK_EVERY_TIME


def test_explicit_tool_rule_overrides_gate_rule():
    engine = PermissionEngine()
    engine.set_gate_rule("commands", PermissionMode.DENY, RiskLevel.EXECUTE)
    engine.set_tool_rule("run_command", PermissionMode.ALWAYS_ALLOW, RiskLevel.EXECUTE)

    decision = engine.evaluate("run_command", RiskLevel.EXECUTE, gate="commands")

    assert decision.allowed is True
    assert decision.source == "tool"


def test_allow_session_requires_session_grant_then_allows():
    engine = PermissionEngine()
    engine.set_tool_rule("write_file", PermissionMode.ALLOW_SESSION, RiskLevel.WRITE)

    before = engine.evaluate("write_file", RiskLevel.WRITE)
    assert before.allowed is False
    assert before.approval_required is True

    engine.grant_session("write_file")
    after = engine.evaluate("write_file", RiskLevel.WRITE)
    assert after.allowed is True
    assert after.approval_required is False

    engine.clear_session()
    cleared = engine.evaluate("write_file", RiskLevel.WRITE)
    assert cleared.allowed is False
    assert cleared.approval_required is True


def test_deny_rule_never_requests_execution_approval():
    engine = PermissionEngine()
    engine.set_tool_rule("desktop_automation", PermissionMode.DENY, RiskLevel.DESKTOP)

    decision = engine.evaluate("desktop_automation", RiskLevel.DESKTOP, gate="desktop")

    assert decision.allowed is False
    assert decision.approval_required is False


def test_risk_above_rule_ceiling_escalates_to_human_approval():
    engine = PermissionEngine()
    engine.set_tool_rule("run_command", PermissionMode.ALWAYS_ALLOW, RiskLevel.WRITE)

    decision = engine.evaluate("run_command", RiskLevel.EXECUTE, gate="commands")

    assert decision.allowed is False
    assert decision.approval_required is True
    assert "exceeds allowed ceiling" in decision.reason


def test_gate_rule_applies_when_no_tool_rule_exists():
    engine = PermissionEngine()
    engine.set_gate_rule("web", PermissionMode.ALWAYS_ALLOW, RiskLevel.EXTERNAL)

    decision = engine.evaluate("search_web", RiskLevel.EXTERNAL, gate="web")

    assert decision.allowed is True
    assert decision.source == "gate"


def test_unknown_risk_is_rejected():
    engine = PermissionEngine()
    try:
        engine.evaluate("tool", "root")
    except ValueError as exc:
        assert "unsupported risk level" in str(exc)
    else:
        raise AssertionError("unknown risk was accepted")


def test_snapshot_exposes_no_hidden_session_authority():
    engine = PermissionEngine(PermissionMode.DENY)
    engine.set_gate_rule("commands", PermissionMode.ALLOW_SESSION, RiskLevel.EXECUTE)
    engine.grant_session("run_command")

    snapshot = engine.snapshot()

    assert snapshot["default_mode"] == "deny"
    assert snapshot["gate_rules"]["commands"] == {"mode": "allow_session", "max_risk": "execute"}
    assert snapshot["session_grants"] == ["run_command"]
