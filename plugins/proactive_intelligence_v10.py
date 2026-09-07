from __future__ import annotations

from app.proactive_dispatch_v10 import ProactiveProposalDispatcher
from app.proactive_intelligence_v10 import ConditionSpec, ProactiveConditionEngine
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

    registry.proactive_intelligence_v10 = engine
    registry.proactive_sources_v10 = sources
    registry.proactive_dispatch_v10 = dispatcher
    registry.proactive_proposals_v10 = proposal_cache

    async def dispatch_cached_proposal(proposal_id, permissions):
        cached = proposal_cache.get(str(proposal_id))
        if cached is None:
            return {"ok": False, "error": "Trusted proactive proposal is not available in the current host session"}
        proposal, evidence = cached
        receipt = await dispatcher.dispatch(proposal, evidence, permissions=dict(permissions))
        return {"ok": receipt.result_ok, "receipt": receipt.to_dict()}

    # Internal runtimes may call this bridge with host-resolved permissions. It is
    # intentionally not registered as a model-visible tool in this checkpoint.
    registry.dispatch_cached_proactive_proposal_v10 = dispatch_cached_proposal

    registry.register(
        name="proactive_v10_status",
        description="Inspect the v10 proactive condition, trusted-source, and dispatch-receipt state without executing actions.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        function=lambda: {
            "ok": True,
            "condition_engine": engine.status(),
            "sources": sources.catalog(),
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
        if result.proposal is not None:
            proposal_cache[result.proposal.proposal_id] = (result.proposal, evidence)
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
