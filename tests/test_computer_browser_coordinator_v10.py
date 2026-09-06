import pytest

from app.computer_browser_adapters_v10 import BrowserAdapter
from app.computer_browser_agent_v10 import (
    ActionKind,
    ActionRisk,
    ComputerAction,
    ComputerMission,
    ScreenElement,
    SurfaceKind as AgentSurfaceKind,
    SurfaceObservation,
)
from app.computer_browser_coordinator_v10 import (
    ComputerBrowserMissionCoordinator,
    ComputerCoordinatorError,
)
from app.computer_browser_driver_v10 import (
    DriverSession,
    DriverSnapshot,
    ElementState,
    SurfaceKind,
    VerificationExpectation,
    VerificationKind,
)


def observation(sequence: int, *, text: str = "Home", url: str = "https://example.test") -> SurfaceObservation:
    return SurfaceObservation(
        surface=AgentSurfaceKind.BROWSER,
        title="Example",
        url=url,
        sequence=sequence,
        elements=(ScreenElement(element_id="go", role="button", label="Go", text=text),),
    )


def snapshot(snapshot_id: str, *, text: str = "Home", url: str = "https://example.test") -> DriverSnapshot:
    return DriverSnapshot(
        snapshot_id=snapshot_id,
        surface=SurfaceKind.BROWSER,
        title="Example",
        url=url,
        elements=(ElementState(element_id="go", text=text),),
    )


def coordinator(*, max_corrections: int = 2, max_recoveries: int = 2) -> ComputerBrowserMissionCoordinator:
    mission = ComputerMission("mission-1", "open the dashboard", max_corrections=max_corrections)
    session = DriverSession("session-1", SurfaceKind.BROWSER, max_recoveries=max_recoveries)
    value = ComputerBrowserMissionCoordinator(mission, session, BrowserAdapter.default())
    value.accept_initial_state(observation=observation(1), snapshot=snapshot("s1"))
    return value


def test_successful_step_records_verified_evidence_and_can_complete():
    value = coordinator()
    result = value.execute_step(
        action=ComputerAction(ActionKind.CLICK, target_id="go", reason="open dashboard"),
        after_observation=observation(2, text="Dashboard", url="https://example.test/dashboard"),
        after_snapshot=snapshot("s2", text="Dashboard", url="https://example.test/dashboard"),
        expectations=(VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),),
    )
    assert result.accepted is True
    assert result.verified is True
    assert result.route == "continue"
    final = value.complete()
    assert final.completed is True
    assert final.actions_recorded == 1
    assert final.driver_receipts == 1


def test_high_risk_action_blocks_without_approval_before_adapter_execution():
    value = coordinator()
    result = value.execute_step(
        action=ComputerAction(ActionKind.CLICK, target_id="go", risk=ActionRisk.HIGH, reason="sensitive click"),
        after_observation=None,
        after_snapshot=None,
        expectations=(VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),),
    )
    assert result.accepted is False
    assert result.route == "blocked"
    assert value.session.receipts == []
    assert value.mission.evidence == []


def test_failed_verification_routes_to_bounded_correction():
    value = coordinator()
    result = value.execute_step(
        action=ComputerAction(ActionKind.CLICK, target_id="go", reason="open dashboard"),
        after_observation=observation(2),
        after_snapshot=snapshot("s2"),
        expectations=(VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),),
    )
    assert result.verified is False
    assert result.route == "correct"
    assert value.mission.corrections == 1
    assert value.session.recoveries == 1


def test_verification_failure_fails_when_driver_recovery_budget_is_zero():
    value = coordinator(max_recoveries=0)
    result = value.execute_step(
        action=ComputerAction(ActionKind.CLICK, target_id="go", reason="open dashboard"),
        after_observation=observation(2),
        after_snapshot=snapshot("s2"),
        expectations=(VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),),
    )
    assert result.route == "failed"
    assert value.mission.failure_reason


def test_complete_refuses_unverified_final_state():
    value = coordinator()
    value.execute_step(
        action=ComputerAction(ActionKind.CLICK, target_id="go", reason="open dashboard"),
        after_observation=observation(2),
        after_snapshot=snapshot("s2"),
        expectations=(VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),),
    )
    with pytest.raises(ComputerCoordinatorError):
        value.complete()


def test_scroll_requires_integer_payload():
    value = coordinator()
    with pytest.raises(ComputerCoordinatorError):
        value.execute_step(
            action=ComputerAction(ActionKind.SCROLL, value="down", reason="scroll page"),
            after_observation=observation(2),
            after_snapshot=snapshot("s2"),
            expectations=(VerificationExpectation(VerificationKind.TITLE_CONTAINS, "Example"),),
        )


def test_accepted_execution_requires_both_agent_and_driver_post_state():
    value = coordinator()
    with pytest.raises(ComputerCoordinatorError):
        value.execute_step(
            action=ComputerAction(ActionKind.CLICK, target_id="go", reason="open dashboard"),
            after_observation=None,
            after_snapshot=snapshot("s2", text="Dashboard"),
            expectations=(VerificationExpectation(VerificationKind.ELEMENT_TEXT_CONTAINS, "Dashboard", target_id="go"),),
        )
