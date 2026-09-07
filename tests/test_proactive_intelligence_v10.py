from pathlib import Path

import pytest

from app.proactive_intelligence_v10 import (
    ConditionSpec,
    ProactiveConditionEngine,
    ProactiveIntelligenceError,
)


CATALOG = [
    {"name": "read_sensor", "risk": "read", "gate": None},
    {"name": "send_external_alert", "risk": "external", "gate": "connectors"},
    {"name": "delete_path", "risk": "destructive", "gate": None},
]


def _engine(tmp_path: Path, timestamps):
    iterator = iter(timestamps)
    return ProactiveConditionEngine(tmp_path / "state.json", clock=lambda: next(iterator))


def test_matching_external_condition_returns_non_executable_approval_proposal(tmp_path: Path):
    engine = _engine(tmp_path, [1000.0])
    spec = ConditionSpec(
        condition_id="tank-temperature-high",
        operator="gte",
        threshold=82,
        action_tool="send_external_alert",
        action_args={"channel": "ops", "message": "temperature high"},
    )

    result = engine.evaluate(spec, 83.5, tool_catalog=CATALOG)

    assert result.matched is True
    assert result.proposed is True
    assert result.proposal is not None
    assert result.proposal.risk == "external"
    assert result.proposal.gate == "connectors"
    assert result.proposal.approval_required is True
    assert result.proposal.execution_authorized is False
    assert engine.status()["execution_capability"] is False


def test_edge_trigger_suppresses_repeated_active_condition_until_reset(tmp_path: Path):
    engine = _engine(tmp_path, [1000.0, 1010.0, 1020.0, 1030.0])
    spec = ConditionSpec("disk-high", "gte", 90, "read_sensor", {}, cooldown_seconds=0, edge_triggered=True)

    first = engine.evaluate(spec, 95, tool_catalog=CATALOG)
    repeated = engine.evaluate(spec, 96, tool_catalog=CATALOG)
    reset = engine.evaluate(spec, 40, tool_catalog=CATALOG)
    retriggered = engine.evaluate(spec, 91, tool_catalog=CATALOG)

    assert first.proposed is True
    assert repeated.proposed is False
    assert repeated.suppressed_reason == "edge_already_active"
    assert reset.matched is False
    assert retriggered.proposed is True


def test_cooldown_suppresses_non_edge_condition_until_elapsed(tmp_path: Path):
    engine = _engine(tmp_path, [1000.0, 1050.0, 1110.0])
    spec = ConditionSpec("queue-depth", "gt", 10, "read_sensor", {}, cooldown_seconds=100, edge_triggered=False)

    assert engine.evaluate(spec, 11, tool_catalog=CATALOG).proposed is True
    second = engine.evaluate(spec, 12, tool_catalog=CATALOG)
    assert second.proposed is False
    assert second.suppressed_reason == "cooldown_active"
    assert engine.evaluate(spec, 13, tool_catalog=CATALOG).proposed is True


def test_destructive_target_is_only_proposed_and_requires_approval(tmp_path: Path):
    engine = _engine(tmp_path, [2000.0])
    spec = ConditionSpec("cleanup-needed", "eq", True, "delete_path", {"path": "generated/tmp.txt"})

    result = engine.evaluate(spec, True, tool_catalog=CATALOG)

    assert result.proposal is not None
    assert result.proposal.risk == "destructive"
    assert result.proposal.approval_required is True
    assert result.proposal.execution_authorized is False


def test_unknown_action_tool_fails_closed_without_fabricating_authority(tmp_path: Path):
    engine = _engine(tmp_path, [3000.0])
    spec = ConditionSpec("unknown", "eq", "ready", "not_registered", {})

    with pytest.raises(ProactiveIntelligenceError, match="not uniquely present"):
        engine.evaluate(spec, "ready", tool_catalog=CATALOG)


def test_corrupt_persistent_state_blocks_evaluation(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text("{broken", encoding="utf-8")
    engine = ProactiveConditionEngine(state, clock=lambda: 4000.0)
    spec = ConditionSpec("safe", "eq", 1, "read_sensor", {})

    with pytest.raises(ProactiveIntelligenceError, match="state is unreadable"):
        engine.evaluate(spec, 1, tool_catalog=CATALOG)


def test_ordered_comparison_rejects_non_numeric_values(tmp_path: Path):
    engine = _engine(tmp_path, [5000.0])
    spec = ConditionSpec("bad-compare", "gt", "high", "read_sensor", {})

    with pytest.raises(ProactiveIntelligenceError, match="ordered comparisons require numeric"):
        engine.evaluate(spec, "higher", tool_catalog=CATALOG)


def test_non_matching_condition_records_checkpoint_without_proposal(tmp_path: Path):
    engine = _engine(tmp_path, [6000.0])
    spec = ConditionSpec("normal", "gt", 50, "read_sensor", {})

    result = engine.evaluate(spec, 20, tool_catalog=CATALOG)

    assert result.matched is False
    assert result.proposed is False
    assert result.proposal is None
    assert len(result.observation_digest) == 64
    assert engine.status()["tracked_conditions"] == 1
