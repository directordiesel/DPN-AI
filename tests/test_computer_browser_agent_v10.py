import pytest

from app.computer_browser_agent_v10 import (
    ActionKind,
    ActionRisk,
    ComputerAction,
    ComputerActionPolicy,
    ComputerAgentError,
    ComputerBrowserAgentRuntime,
    ComputerMission,
    ScreenElement,
    SurfaceKind,
    SurfaceObservation,
)


def observation(sequence=1, *, text="Open", enabled=True):
    return SurfaceObservation(
        surface=SurfaceKind.BROWSER,
        title="Test",
        url="https://example.test",
        sequence=sequence,
        elements=(ScreenElement("btn-1", "button", label=text, enabled=enabled),),
    )


def test_select_target_requires_unique_enabled_match():
    target = ComputerBrowserAgentRuntime.select_target(observation(), role="button", label="Open")
    assert target.element_id == "btn-1"


def test_select_target_rejects_missing_match():
    with pytest.raises(ComputerAgentError):
        ComputerBrowserAgentRuntime.select_target(observation(), role="textbox")


def test_select_target_rejects_ambiguous_match():
    obs = SurfaceObservation(
        surface=SurfaceKind.DESKTOP,
        title="Ambiguous",
        sequence=1,
        elements=(
            ScreenElement("a", "button", label="Save"),
            ScreenElement("b", "button", label="Save"),
        ),
    )
    with pytest.raises(ComputerAgentError):
        ComputerBrowserAgentRuntime.select_target(obs, role="button", label="Save")


def test_high_risk_action_requires_approval():
    action = ComputerAction(ActionKind.CLICK, target_id="delete", risk=ActionRisk.HIGH, destructive=True, reason="delete record")
    denied = ComputerActionPolicy.evaluate(action)
    approved = ComputerActionPolicy.evaluate(action, approval_granted=True)
    assert denied.allowed is False and denied.approval_required is True
    assert approved.allowed is True


def test_critical_action_is_denied_even_with_approval_flag():
    action = ComputerAction(ActionKind.CLICK, target_id="wipe", risk=ActionRisk.CRITICAL, destructive=True, reason="wipe system")
    decision = ComputerActionPolicy.evaluate(action, approval_granted=True)
    assert decision.allowed is False
    assert decision.approval_required is True


def test_verify_action_uses_fresh_observation_and_expected_text():
    before = observation(1, text="Open")
    after = SurfaceObservation(
        surface=SurfaceKind.BROWSER,
        title="Test",
        url="https://example.test",
        sequence=2,
        elements=(ScreenElement("status", "status", text="Saved successfully"),),
    )
    action = ComputerAction(ActionKind.CLICK, target_id="btn-1", reason="open item")
    evidence = ComputerBrowserAgentRuntime.verify_action(before, after, action, expected_text="Saved successfully")
    assert evidence.success is True
    assert evidence.observed_change is True


def test_verify_action_rejects_stale_observation():
    action = ComputerAction(ActionKind.CLICK, target_id="btn-1", reason="open item")
    with pytest.raises(ComputerAgentError):
        ComputerBrowserAgentRuntime.verify_action(observation(2), observation(2), action)


def test_failed_verification_routes_to_bounded_correction():
    mission = ComputerMission("m1", "click working control", max_corrections=1)
    before = observation(1)
    after = SurfaceObservation(surface=SurfaceKind.BROWSER, title="Test", sequence=2, elements=before.elements)
    action = ComputerAction(ActionKind.CLICK, target_id="btn-1", reason="open item")
    evidence = ComputerBrowserAgentRuntime.verify_action(before, after, action, expected_text="missing")
    assert ComputerBrowserAgentRuntime.route_after_verification(mission, evidence) == "correct"
    assert mission.corrections == 1


def test_correction_budget_exhaustion_fails_closed():
    mission = ComputerMission("m1", "click working control", max_corrections=0)
    before = observation(1)
    after = SurfaceObservation(surface=SurfaceKind.BROWSER, title="Test", sequence=2, elements=before.elements)
    action = ComputerAction(ActionKind.CLICK, target_id="btn-1", reason="open item")
    evidence = ComputerBrowserAgentRuntime.verify_action(before, after, action, expected_text="missing")
    assert ComputerBrowserAgentRuntime.route_after_verification(mission, evidence) == "failed"
    assert mission.failure_reason


def test_mission_completion_requires_successful_evidence():
    mission = ComputerMission("m1", "finish task")
    with pytest.raises(ComputerAgentError):
        mission.complete()


def test_observation_sequences_must_increase():
    mission = ComputerMission("m1", "observe")
    mission.observe(observation(1))
    with pytest.raises(ComputerAgentError):
        mission.observe(observation(1))
