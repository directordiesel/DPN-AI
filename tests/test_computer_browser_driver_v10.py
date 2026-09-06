import pytest

from app.computer_browser_driver_v10 import (
    DriverAction,
    DriverCommand,
    DriverContractError,
    DriverReceipt,
    DriverRecoveryPolicy,
    DriverSession,
    DriverSnapshot,
    DriverVerifier,
    ElementState,
    SurfaceKind,
    VerificationExpectation,
    VerificationKind,
)


def browser_snapshot(snapshot_id="s1", *, url="https://example.test/login", value="", visible=True, enabled=True):
    return DriverSnapshot(
        snapshot_id=snapshot_id,
        surface=SurfaceKind.BROWSER,
        title="DPN Login",
        url=url,
        active_window="DPN Browser",
        elements=(ElementState("email", "Email", value=value, visible=visible, enabled=enabled),),
    )


def test_driver_command_requires_target_for_click():
    with pytest.raises(DriverContractError):
        DriverCommand(DriverAction.CLICK).validate()


def test_navigate_requires_url():
    with pytest.raises(DriverContractError):
        DriverCommand(DriverAction.NAVIGATE).validate()


def test_session_requires_snapshot_to_advance():
    session = DriverSession("session-1", SurfaceKind.BROWSER)
    session.record_snapshot(browser_snapshot("s1"))
    with pytest.raises(DriverContractError):
        session.record_snapshot(browser_snapshot("s1"))


def test_session_rejects_wrong_surface():
    session = DriverSession("session-1", SurfaceKind.DESKTOP)
    with pytest.raises(DriverContractError):
        session.record_snapshot(browser_snapshot("s1"))


def test_receipt_must_reference_latest_snapshot():
    session = DriverSession("session-1", SurfaceKind.BROWSER)
    session.record_snapshot(browser_snapshot("s1"))
    receipt = DriverReceipt(DriverCommand(DriverAction.CLICK, target_id="email"), True, "stale", "s2")
    with pytest.raises(DriverContractError):
        session.record_receipt(receipt)


def test_accepted_receipt_requires_after_snapshot_id():
    with pytest.raises(DriverContractError):
        DriverReceipt(DriverCommand(DriverAction.CLICK, target_id="email"), True, "s1").validate()


def test_url_and_title_verification_passes():
    snapshot = browser_snapshot(url="https://example.test/dashboard")
    result = DriverVerifier.verify(
        snapshot,
        (
            VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),
            VerificationExpectation(VerificationKind.TITLE_CONTAINS, "DPN"),
        ),
    )
    assert result.passed
    assert result.failures == ()


def test_element_value_verification_passes():
    result = DriverVerifier.verify(
        browser_snapshot(value="diesel@dpn.test"),
        (VerificationExpectation(VerificationKind.ELEMENT_VALUE_EQUALS, "diesel@dpn.test", "email"),),
    )
    assert result.passed


def test_missing_element_fails_closed():
    result = DriverVerifier.verify(
        browser_snapshot(),
        (VerificationExpectation(VerificationKind.ELEMENT_VISIBLE, True, "password"),),
    )
    assert not result.passed
    assert "missing element:password" in result.failures


def test_verification_requires_expectation():
    with pytest.raises(DriverContractError):
        DriverVerifier.verify(browser_snapshot(), ())


def test_recovery_policy_allows_bounded_retry_after_accepted_action():
    session = DriverSession("session-1", SurfaceKind.BROWSER, max_recoveries=1)
    before = browser_snapshot("s1")
    after = browser_snapshot("s2")
    session.record_snapshot(before)
    receipt = DriverReceipt(DriverCommand(DriverAction.TYPE, target_id="email", text="x"), True, "s1", "s2")
    session.record_receipt(receipt)
    session.record_snapshot(after)
    verification = DriverVerifier.verify(
        after,
        (VerificationExpectation(VerificationKind.ELEMENT_VALUE_EQUALS, "x", "email"),),
    )
    assert not verification.passed
    assert DriverRecoveryPolicy.can_retry(session, last_receipt=receipt, verification=verification)
    session.record_recovery()
    assert not DriverRecoveryPolicy.can_retry(session, last_receipt=receipt, verification=verification)


def test_rejected_action_is_not_retryable():
    session = DriverSession("session-1", SurfaceKind.BROWSER)
    session.record_snapshot(browser_snapshot("s1"))
    receipt = DriverReceipt(DriverCommand(DriverAction.CLICK, target_id="email"), False, "s1", detail="blocked")
    receipt.validate()
    result = DriverVerifier.verify(
        browser_snapshot("s2"),
        (VerificationExpectation(VerificationKind.URL_CONTAINS, "dashboard"),),
    )
    assert not DriverRecoveryPolicy.can_retry(session, last_receipt=receipt, verification=result)


def test_post_action_snapshot_must_be_recorded_exactly_once():
    session = DriverSession("session-1", SurfaceKind.BROWSER)
    session.record_snapshot(browser_snapshot("s1"))
    receipt = DriverReceipt(DriverCommand(DriverAction.CLICK, target_id="email"), True, "s1", "s2")
    session.record_receipt(receipt)
    with pytest.raises(DriverContractError):
        DriverRecoveryPolicy.require_fresh_post_action_snapshot(session, receipt)
    session.record_snapshot(browser_snapshot("s2"))
    assert DriverRecoveryPolicy.require_fresh_post_action_snapshot(session, receipt).snapshot_id == "s2"
