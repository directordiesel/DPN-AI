from pathlib import Path

import pytest

from app.proactive_intelligence_v10 import ProactiveConditionEngine
from app.proactive_lifecycle_v10 import ProactiveConditionLifecycle, ProactiveLifecycleError
from app.proactive_sources_v10 import ProactiveSourceRegistry, SourceContract


def _catalog():
    return [
        {"name": "read_status", "risk": "read", "gate": None},
        {"name": "send_external", "risk": "external", "gate": "connector"},
    ]


def _lifecycle(tmp_path: Path, clock_value=1000.0):
    clock = lambda: clock_value
    engine = ProactiveConditionEngine(tmp_path / "engine.json", clock=clock)
    sources = ProactiveSourceRegistry(clock=clock)
    sources.register_source(SourceContract("system.load", max_age_seconds=60), lambda: 7)
    captured = []
    lifecycle = ProactiveConditionLifecycle(
        tmp_path / "definitions.json",
        engine=engine,
        sources=sources,
        tool_catalog=_catalog,
        proposal_sink=lambda evaluation, evidence: captured.append((evaluation, evidence)),
        clock=clock,
    )
    return lifecycle, captured


def test_new_definition_is_persistent_and_disabled_by_default(tmp_path):
    lifecycle, _ = _lifecycle(tmp_path)
    created = lifecycle.register(
        condition_id="high-load",
        source_id="system.load",
        operator="gte",
        threshold=5,
        action_tool="read_status",
        interval_seconds=60,
    )
    assert created.enabled is False
    assert lifecycle.status()["enabled"] == 0

    reloaded, _ = _lifecycle(tmp_path)
    assert reloaded.get("high-load") is not None
    assert reloaded.get("high-load").enabled is False


def test_enabled_due_condition_evaluates_and_caches_proposal(tmp_path):
    lifecycle, captured = _lifecycle(tmp_path)
    lifecycle.register(
        condition_id="high-load",
        source_id="system.load",
        operator="gte",
        threshold=5,
        action_tool="send_external",
        interval_seconds=60,
    )
    lifecycle.set_enabled("high-load", True)
    results = lifecycle.evaluate_due()
    assert len(results) == 1
    assert results[0].evaluated is True
    assert results[0].evaluation is not None
    assert results[0].evaluation.proposed is True
    assert results[0].evaluation.proposal.approval_required is True
    assert results[0].evaluation.proposal.execution_authorized is False
    assert len(captured) == 1


def test_due_evaluation_does_not_dispatch_or_re_run_before_due(tmp_path):
    lifecycle, captured = _lifecycle(tmp_path)
    lifecycle.register(
        condition_id="high-load",
        source_id="system.load",
        operator="gte",
        threshold=5,
        action_tool="read_status",
        interval_seconds=60,
    )
    lifecycle.set_enabled("high-load", True)
    first = lifecycle.evaluate_due()
    second = lifecycle.evaluate_due()
    assert len(first) == 1
    assert second == []
    assert len(captured) == 1
    assert lifecycle.status()["dispatch_capability"] is False


def test_unknown_source_is_rejected_before_persistence(tmp_path):
    lifecycle, _ = _lifecycle(tmp_path)
    with pytest.raises(ProactiveLifecycleError, match="not registered"):
        lifecycle.register(
            condition_id="bad",
            source_id="caller.fake",
            operator="eq",
            threshold=1,
            action_tool="read_status",
        )
    assert lifecycle.list_definitions() == []


def test_corrupt_lifecycle_state_blocks_operations(tmp_path):
    lifecycle, _ = _lifecycle(tmp_path)
    lifecycle.path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ProactiveLifecycleError, match="unreadable"):
        lifecycle.list_definitions()


def test_disabled_definition_never_collects_or_evaluates(tmp_path):
    calls = []
    clock = lambda: 1000.0
    engine = ProactiveConditionEngine(tmp_path / "engine.json", clock=clock)
    sources = ProactiveSourceRegistry(clock=clock)
    sources.register_source(SourceContract("system.load", max_age_seconds=60), lambda: calls.append(1) or 7)
    lifecycle = ProactiveConditionLifecycle(
        tmp_path / "definitions.json",
        engine=engine,
        sources=sources,
        tool_catalog=_catalog,
        clock=clock,
    )
    lifecycle.register(
        condition_id="disabled",
        source_id="system.load",
        operator="gte",
        threshold=5,
        action_tool="read_status",
    )
    assert lifecycle.evaluate_due() == []
    assert calls == []


def test_interval_bounds_are_fail_closed(tmp_path):
    lifecycle, _ = _lifecycle(tmp_path)
    with pytest.raises(ProactiveLifecycleError, match="interval_seconds"):
        lifecycle.register(
            condition_id="too-fast",
            source_id="system.load",
            operator="gte",
            threshold=5,
            action_tool="read_status",
            interval_seconds=1,
        )
