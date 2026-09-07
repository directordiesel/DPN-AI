from __future__ import annotations

from app.proactive_dispatch_v10 import ProactiveProposalDispatcher
from app.proactive_intelligence_v10 import ConditionSpec, ProactiveConditionEngine
from app.proactive_lifecycle_v10 import ProactiveConditionLifecycle
from app.proactive_sources_v10 import ProactiveSourceRegistry, SourceContract


def register(registry):
    engine = ProactiveConditionEngine(registry.settings.data_dir / "proactive_v10_state.json")
    sources = ProactiveSourceRegistry()
    dispatcher = ProactiveProposalDispatcher(registry, registry.settings.data_dir / "proactive_v10_dispatch_receipts.json")
    proposal_cache = {}

    # Host-owned source registration. Model-visible calls can collect these sources
    # but cannot register new sources or upgrade trust/freshness contracts.
    sources.register_source(
        SourceContract("system.pending_approvals", max_age_seconds=30, trusted_for_dispatch=True),
        lambda: len(registry.db.list_approvals("pending", 1000)),
    )
    sources.register_source(
        SourceContract("system.active_missions", max_age_seconds=60, trusted_for_dispatch=True),
        lambda: sum(
            1
            for mission in registry.db.list_missions(limit=1000)
            if str(mission.get("status") or "").lower() not in {"completed", "failed", "cancelled"}
        ),
    )
    sources.register_source(
        SourceContract("system.enabled_connectors", max_age_seconds=60, trusted_for_dispatch=True),
        lambda: sum(
            1
            for connector in (registry.connectors.list().get("connectors") or [])
            if bool(connector.get("enabled", False))
        ),
    )

    def cache_proposal(evaluation, evidence):
        if evaluation.proposal is not None:
            proposal_cache[evaluation.proposal.proposal_id] = (evaluation.proposal, evidence)

    lifecycle = ProactiveConditionLifecycle(
        registry.settings.data_dir / "proactive_v10_definitions.json",
        engine=engine,
        sources=sources,
        tool_catalog=registry.catalog,
        proposal_sink=cache_proposal,
    )

    registry.proactive_intelligence_v10 = engine
    registry.proactive_sources_v10 = sources
    registry.proactive_dispatch_v10 = dispatcher
    registry.proactive_lifecycle_v10 = lifecycle
    registry.proactive_proposals_v10 = proposal_cache

    async def dispatch_cached_proposal(proposal_id, permissions):
        cached = proposal_cache.get(str(proposal_id))
        if cached is None:
            return {"ok": False, "error": "Trusted proactive proposal is not available in the current host session"}
        proposal, evidence = cached
        receipt = await dispatcher.dispatch(proposal, evidence, permissions=dict(permissions))
        return {"ok": receipt.result_ok, "receipt": receipt.to_dict()}

    # Internal runtimes may call these bridges with host-resolved permissions/state.
    # They are intentionally not registered as model-visible tools.
    registry.dispatch_cached_proactive_proposal_v10 = dispatch_cached_proposal
    registry.evaluate_due_proactive_conditions_v10 = lifecycle.evaluate_due

    registry.register(
        name="proactive_v10_status",
        description="Inspect the v10 proactive condition, trusted-source, persistent-lifecycle, and dispatch-receipt state without executing actions.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {
            "ok": True,
            "condition_engine": engine.status(),
            "sources": sources.catalog(),
            "lifecycle": lifecycle.status(),
            "dispatcher": dispatcher.status(),
            "cached_proposals": len(proposal_cache),
        },
        risk="read",
    )

    def evaluate_condition(condition_id, operator, threshold, observed_value, action_tool, action_args=None, cooldown_seconds=300, edge_triggered=True):
        spec = ConditionSpec(condition_id, operator, threshold, action_tool, action_args or {}, cooldown_seconds, edge_triggered)
        result = engine.evaluate(spec, observed_value, tool_catalog=registry.catalog())
        return {"ok": True, **result.to_dict()}

    registry.register(
        name="evaluate_proactive_condition",
        description=(
            "Evaluate one bounded caller-supplied observation and return a non-executable proposal. Caller-supplied observations are explicitly untrusted and cannot enter proactive dispatch."
        ),
        parameters={
            "type": "object",
            "properties": {
                "condition_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte"]},
                "threshold": {}, "observed_value": {},
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

    def evaluate_trusted_source(condition_id, source_id, operator, threshold, action_tool, action_args=None, cooldown_seconds=300, edge_triggered=True):
        evidence = sources.collect(source_id)
        spec = ConditionSpec(condition_id, operator, threshold, action_tool, action_args or {}, cooldown_seconds, edge_triggered)
        result = engine.evaluate_evidence(spec, evidence, tool_catalog=registry.catalog())
        cache_proposal(result, evidence)
        return {"ok": True, "evidence": evidence.to_dict(), **result.to_dict()}

    registry.register(
        name="evaluate_trusted_proactive_source",
        description=(
            "Collect one host-registered trusted condition source and evaluate it against a bounded condition. Matching proposals are cached host-side for later approval-preserving dispatch; this tool does not execute them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "condition_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "source_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte"]},
                "threshold": {},
                "action_tool": {"type": "string", "minLength": 1, "maxLength": 120},
                "action_args": {"type": "object", "default": {}},
                "cooldown_seconds": {"type": "integer", "minimum": 0, "maximum": 604800, "default": 300},
                "edge_triggered": {"type": "boolean", "default": True},
            },
            "required": ["condition_id", "source_id", "operator", "threshold", "action_tool"],
            "additionalProperties": False,
        },
        function=evaluate_trusted_source,
        risk="write",
    )

    registry.register(
        name="list_proactive_conditions_v10",
        description="List persistent v10 condition definitions and enabled state. This is read-only and does not evaluate or dispatch actions.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {"ok": True, "definitions": [item.__dict__ for item in lifecycle.list_definitions()]},
        risk="read",
    )

    def register_condition(condition_id, source_id, operator, threshold, action_tool, action_args=None, interval_seconds=300, cooldown_seconds=300, edge_triggered=True):
        definition = lifecycle.register(
            condition_id=condition_id,
            source_id=source_id,
            operator=operator,
            threshold=threshold,
            action_tool=action_tool,
            action_args=action_args or {},
            interval_seconds=interval_seconds,
            cooldown_seconds=cooldown_seconds,
            edge_triggered=edge_triggered,
        )
        return {"ok": True, "definition": definition.__dict__, "enabled": False, "dispatch_performed": False}

    registry.register(
        name="register_proactive_condition_v10",
        description="Persist a bounded trusted-source condition definition. New definitions are always disabled and cannot dispatch until separately enabled by the host/user.",
        parameters={
            "type": "object",
            "properties": {
                "condition_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "source_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "operator": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte"]},
                "threshold": {},
                "action_tool": {"type": "string", "minLength": 1, "maxLength": 120},
                "action_args": {"type": "object", "default": {}},
                "interval_seconds": {"type": "integer", "minimum": 30, "maximum": 86400, "default": 300},
                "cooldown_seconds": {"type": "integer", "minimum": 0, "maximum": 604800, "default": 300},
                "edge_triggered": {"type": "boolean", "default": True},
            },
            "required": ["condition_id", "source_id", "operator", "threshold", "action_tool"],
            "additionalProperties": False,
        },
        function=register_condition,
        risk="write",
    )

    registry.register(
        name="set_proactive_condition_enabled_v10",
        description="Enable or disable one persisted proactive condition. This changes lifecycle state but does not evaluate or dispatch the condition.",
        parameters={
            "type": "object",
            "properties": {
                "condition_id": {"type": "string", "minLength": 1, "maxLength": 120},
                "enabled": {"type": "boolean"},
            },
            "required": ["condition_id", "enabled"],
            "additionalProperties": False,
        },
        function=lambda condition_id, enabled: {"ok": True, "definition": lifecycle.set_enabled(condition_id, enabled).__dict__, "dispatch_performed": False},
        risk="write",
    )
