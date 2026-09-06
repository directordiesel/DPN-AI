import pytest

from app.capability_readiness_v9 import CapabilityReadiness, CapabilityRegistry
from app.readiness_diagnostics_v9 import summarize_readiness


def _cap(name: str, *, implemented=True, configured=True, permission_enabled=True, live=True):
    return CapabilityReadiness(
        name=name,
        implemented=implemented,
        configured=configured,
        permission_enabled=permission_enabled,
        live=live,
        reason=f"{name} readiness",
    )


def test_readiness_summary_classifies_first_blocking_stage():
    registry = CapabilityRegistry(
        capabilities=(
            _cap("ready"),
            _cap("impl", implemented=False, configured=False, permission_enabled=False, live=False),
            _cap("config", configured=False, permission_enabled=False, live=False),
            _cap("permission", permission_enabled=False, live=False),
            _cap("verification", live=False),
        )
    )
    summary = summarize_readiness(registry)
    assert summary.rc_ready is False
    assert summary.total == 5
    assert summary.live == 1
    assert summary.blocked == 4
    assert [(item.capability, item.stage) for item in summary.blockers] == [
        ("impl", "implementation"),
        ("config", "configuration"),
        ("permission", "permission"),
        ("verification", "verification"),
    ]


def test_required_subset_can_be_ready_without_claiming_unselected_capabilities():
    registry = CapabilityRegistry(capabilities=(_cap("local_models"), _cap("vision", live=False)))
    summary = summarize_readiness(registry, required_capabilities=("local_models",))
    assert summary.rc_ready is True
    assert summary.total == 1
    assert summary.live == 1
    assert summary.blockers == ()


def test_unknown_required_capability_fails_closed():
    registry = CapabilityRegistry(capabilities=(_cap("local_models"),))
    with pytest.raises(ValueError, match="unknown required capability"):
        summarize_readiness(registry, required_capabilities=("does_not_exist",))


def test_duplicate_registry_entries_are_rejected():
    registry = CapabilityRegistry(capabilities=(_cap("voice"), _cap("voice")))
    with pytest.raises(ValueError, match="duplicate capability"):
        summarize_readiness(registry)


def test_payload_contains_no_configuration_or_secret_values():
    registry = CapabilityRegistry(capabilities=(_cap("vision", live=False),))
    payload = summarize_readiness(registry).payload()
    text = repr(payload).lower()
    assert "api_key" not in text
    assert "token" not in text
    assert "url" not in text
    assert payload["blockers"][0]["stage"] == "verification"
