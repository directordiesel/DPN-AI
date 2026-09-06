from __future__ import annotations

import pytest

from app.computer_browser_adapters_v10 import (
    AdapterCapability,
    AdapterDescriptor,
    AdapterExecutionGate,
    AdapterHealth,
    BrowserAdapter,
    ExecutionPolicy,
    PlatformAdapter,
    WindowsDesktopAdapter,
)
from app.computer_browser_driver_v10 import (
    DriverAction,
    DriverCommand,
    DriverContractError,
    DriverSession,
    DriverSnapshot,
    SurfaceKind,
)


def browser_snapshot(snapshot_id: str, *, url: str = "https://example.test") -> DriverSnapshot:
    return DriverSnapshot(snapshot_id=snapshot_id, surface=SurfaceKind.BROWSER, title="Example", url=url)


def test_descriptor_requires_capabilities() -> None:
    descriptor = AdapterDescriptor("browser", SurfaceKind.BROWSER, ())
    with pytest.raises(DriverContractError):
        descriptor.validate()


def test_unavailable_adapter_fails_closed() -> None:
    descriptor = AdapterDescriptor(
        "browser",
        SurfaceKind.BROWSER,
        (AdapterCapability.OBSERVE, AdapterCapability.NAVIGATE),
        health=AdapterHealth.UNAVAILABLE,
    )
    policy = ExecutionPolicy((AdapterCapability.OBSERVE, AdapterCapability.NAVIGATE))
    allowed, reason = AdapterExecutionGate.authorize(
        descriptor,
        policy,
        DriverCommand(DriverAction.NAVIGATE, url="https://example.test"),
    )
    assert not allowed
    assert "unavailable" in reason


def test_missing_capability_is_denied() -> None:
    descriptor = AdapterDescriptor("desktop", SurfaceKind.DESKTOP, (AdapterCapability.OBSERVE,))
    policy = ExecutionPolicy((AdapterCapability.OBSERVE,))
    allowed, reason = AdapterExecutionGate.authorize(
        descriptor,
        policy,
        DriverCommand(DriverAction.CLICK, target_id="save"),
    )
    assert not allowed
    assert "does not support click" in reason


def test_policy_denies_unapproved_capability() -> None:
    descriptor = AdapterDescriptor(
        "browser",
        SurfaceKind.BROWSER,
        (AdapterCapability.OBSERVE, AdapterCapability.CLICK),
    )
    policy = ExecutionPolicy((AdapterCapability.OBSERVE,))
    allowed, reason = AdapterExecutionGate.authorize(
        descriptor,
        policy,
        DriverCommand(DriverAction.CLICK, target_id="save"),
    )
    assert not allowed
    assert "policy does not allow click" in reason


def test_action_specific_approval_gate() -> None:
    descriptor = AdapterDescriptor(
        "browser",
        SurfaceKind.BROWSER,
        (AdapterCapability.OBSERVE, AdapterCapability.NAVIGATE),
    )
    policy = ExecutionPolicy(
        (AdapterCapability.OBSERVE, AdapterCapability.NAVIGATE),
        approval_required_actions=(DriverAction.NAVIGATE,),
    )
    command = DriverCommand(DriverAction.NAVIGATE, url="https://example.test/admin")
    denied, _ = AdapterExecutionGate.authorize(descriptor, policy, command)
    allowed, _ = AdapterExecutionGate.authorize(descriptor, policy, command, approval_granted=True)
    assert not denied
    assert allowed


def test_browser_adapter_accepts_concrete_observation() -> None:
    adapter = BrowserAdapter.default()
    session = DriverSession("s1", SurfaceKind.BROWSER)
    adapter.accept_snapshot(session, browser_snapshot("before"))
    assert session.snapshots[-1].snapshot_id == "before"


def test_adapter_rejects_surface_mismatch() -> None:
    adapter = BrowserAdapter.default()
    session = DriverSession("s1", SurfaceKind.BROWSER)
    snapshot = DriverSnapshot("before", SurfaceKind.DESKTOP, active_window="Notepad")
    with pytest.raises(DriverContractError):
        adapter.accept_snapshot(session, snapshot)


def test_authorized_action_requires_post_action_evidence() -> None:
    adapter = BrowserAdapter.default()
    session = DriverSession("s1", SurfaceKind.BROWSER)
    adapter.accept_snapshot(session, browser_snapshot("before"))
    with pytest.raises(DriverContractError):
        adapter.build_execution_receipt(
            session,
            DriverCommand(DriverAction.NAVIGATE, url="https://example.test/next"),
            after_snapshot=None,
        )


def test_authorized_action_records_fresh_receipt() -> None:
    adapter = BrowserAdapter.default()
    session = DriverSession("s1", SurfaceKind.BROWSER)
    adapter.accept_snapshot(session, browser_snapshot("before"))
    receipt = adapter.build_execution_receipt(
        session,
        DriverCommand(DriverAction.NAVIGATE, url="https://example.test/next"),
        after_snapshot=browser_snapshot("after", url="https://example.test/next"),
    )
    assert receipt.accepted
    assert receipt.before_snapshot_id == "before"
    assert receipt.after_snapshot_id == "after"
    assert len(session.receipts) == 1


def test_authorized_action_rejects_stale_snapshot_id() -> None:
    adapter = BrowserAdapter.default()
    session = DriverSession("s1", SurfaceKind.BROWSER)
    adapter.accept_snapshot(session, browser_snapshot("same"))
    with pytest.raises(DriverContractError):
        adapter.build_execution_receipt(
            session,
            DriverCommand(DriverAction.NAVIGATE, url="https://example.test/next"),
            after_snapshot=browser_snapshot("same", url="https://example.test/next"),
        )


def test_rejected_action_does_not_mutate_session() -> None:
    descriptor = AdapterDescriptor("browser", SurfaceKind.BROWSER, (AdapterCapability.OBSERVE,))
    adapter = PlatformAdapter(descriptor, ExecutionPolicy((AdapterCapability.OBSERVE,)))
    session = DriverSession("s1", SurfaceKind.BROWSER)
    adapter.accept_snapshot(session, browser_snapshot("before"))
    receipt = adapter.build_execution_receipt(
        session,
        DriverCommand(DriverAction.CLICK, target_id="save"),
        after_snapshot=None,
    )
    assert not receipt.accepted
    assert len(session.snapshots) == 1
    assert session.receipts == []


def test_default_adapters_expose_expected_surface_capabilities() -> None:
    browser = BrowserAdapter.default()
    desktop = WindowsDesktopAdapter.default()
    assert browser.descriptor.surface == SurfaceKind.BROWSER
    assert browser.descriptor.supports(AdapterCapability.URL_STATE)
    assert desktop.descriptor.surface == SurfaceKind.DESKTOP
    assert desktop.descriptor.supports(AdapterCapability.WINDOW_ENUMERATION)
    assert not desktop.descriptor.supports(AdapterCapability.NAVIGATE)
