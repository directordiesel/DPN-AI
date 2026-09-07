from __future__ import annotations

from app.proactive_intelligence_v10 import ConditionSpec, ProactiveConditionEngine


def register(registry):
    engine = ProactiveConditionEngine(registry.settings.data_dir / "proactive_v10_state.json")
    registry.proactive_intelligence_v10 = engine

    registry.register(
        name="proactive_v10_status",
        description="Inspect the v10 proactive condition engine. This runtime can evaluate and propose actions but cannot dispatch them.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=engine.status,
        risk="read",
    )

    def evaluate_condition(condition_id, operator, threshold, observed_value, action_tool, action_args=None, cooldown_seconds=300, edge_triggered=True):
        spec = ConditionSpec(
            condition_id=condition_id,
            operator=operator,
            threshold=threshold,
            action_tool=action_tool,
            action_args=action_args or {},
            cooldown_seconds=cooldown_seconds,
            edge_triggered=edge_triggered,
        )
        result = engine.evaluate(spec, observed_value, tool_catalog=registry.catalog())
        return {"ok": True, **result.to_dict()}

    registry.register(
        name="evaluate_proactive_condition",
        description=(
            "Evaluate one bounded proactive condition against a supplied observation and, when matched, return a non-executable action proposal "
            "carrying the target tool's current risk and permission gate. This tool never dispatches the proposed action."
        ),
        parameters={
            "type": "object",
            "properties": {
                "condition_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte"]},
                "threshold": {},
                "observed_value": {},
                "action_tool": {"type": "string", "minLength": 1, "maxLength": 120},
                "action_args": {"type": "object", "default": {}},
                "cooldown_seconds": {"type": "integer", "minimum": 0, "maximum": 604800, "default": 300},
                "edge_triggered": {"type": "boolean", "default": True},
            },
            "required": ["condition_id", "operator", "threshold", "observed_value", "action_tool"],
            "additionalProperties": False,
        },
        function=evaluate_condition,
        risk="write",
    )
