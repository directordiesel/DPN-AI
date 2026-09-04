from __future__ import annotations

from typing import Any


_MODES = {"research", "compare", "verify", "monitor", "browse"}
_DEPTHS = {"quick", "standard", "deep"}
_OUTPUTS = {"answer", "brief", "report", "evidence_bundle", "document_package"}


def build_research_browser_plan(
    objective: str,
    mode: str = "research",
    depth: str = "standard",
    output: str = "report",
    require_current_information: bool = True,
    require_citations: bool = True,
    max_sources: int = 12,
    allow_browser_actions: bool = False,
) -> dict[str, Any]:
    mode = str(mode or "research").strip().lower()
    depth = str(depth or "standard").strip().lower()
    output = str(output or "report").strip().lower()
    if mode not in _MODES:
        mode = "research"
    if depth not in _DEPTHS:
        depth = "standard"
    if output not in _OUTPUTS:
        output = "report"

    source_cap = max(1, min(int(max_sources), 30))
    target_sources = {
        "quick": min(source_cap, 5),
        "standard": min(source_cap, 12),
        "deep": min(source_cap, 30),
    }[depth]

    stages: list[dict[str, Any]] = [
        {
            "name": "frame_question",
            "purpose": "Convert the objective into answerable research questions, scope boundaries, freshness needs, and acceptance criteria.",
        },
        {
            "name": "source_strategy",
            "purpose": "Prioritize primary, official, authoritative, and directly relevant sources before secondary commentary.",
            "target_sources": target_sources,
        },
        {
            "name": "discover",
            "purpose": "Discover candidate sources using available research, browser, connector, and knowledge tools without inventing unavailable access.",
        },
        {
            "name": "retrieve",
            "purpose": "Open the strongest candidate sources and capture URLs, titles, dates, publishers, relevant evidence, and retrieval context.",
        },
        {
            "name": "evaluate_sources",
            "purpose": "Assess authority, recency, directness, independence, conflicts, and gaps before synthesis.",
        },
    ]
    if mode in {"compare", "verify"}:
        stages.append({
            "name": "cross_check",
            "purpose": "Compare material claims across independent sources and identify agreements, contradictions, unresolved uncertainty, and stale evidence.",
        })
    if mode == "browse":
        stages.append({
            "name": "browser_workflow",
            "purpose": "Use bounded browser navigation only when page interaction is necessary; preserve screenshots and final URLs as evidence.",
            "browser_actions_allowed": bool(allow_browser_actions),
        })
    if mode == "monitor":
        stages.append({
            "name": "change_baseline",
            "purpose": "Define the facts, pages, timestamps, or conditions that future runs would compare. This plan does not itself schedule future execution.",
        })
    stages.extend([
        {
            "name": "synthesize",
            "purpose": "Separate sourced facts from inference, calculate confidence from the evidence set, and answer the research questions directly.",
        },
        {
            "name": "citation_audit",
            "purpose": "Ensure material factual claims are traceable to captured sources and citation targets are not fabricated.",
            "required": bool(require_citations),
        },
        {
            "name": "deliver",
            "purpose": "Return the requested output with findings, evidence, dates, uncertainty, limitations, and exact generated artifact paths when applicable.",
        },
    ])

    quality_gates = [
        "objective_answered",
        "source_urls_captured",
        "source_dates_recorded_when_available",
        "authority_and_recency_evaluated",
        "fact_inference_separation",
        "contradictions_reported",
    ]
    if require_current_information:
        quality_gates.append("freshness_verified")
    if require_citations:
        quality_gates.append("material_claims_cited")

    return {
        "ok": True,
        "objective": objective.strip(),
        "mode": mode,
        "depth": depth,
        "output": output,
        "require_current_information": bool(require_current_information),
        "require_citations": bool(require_citations),
        "max_sources": source_cap,
        "target_sources": target_sources,
        "required_capabilities": [
            "research",
            "browser",
            "knowledge_search",
            "source_evaluation",
            "citation_audit",
            "artifact_creation" if output in {"report", "document_package"} else "structured_response",
        ],
        "preferred_source_order": [
            "primary_or_official",
            "authoritative_direct_source",
            "high_quality_independent_secondary",
            "community_or_anecdotal_when_relevant",
        ],
        "quality_gates": quality_gates,
        "execution_policy": {
            "never_invent_sources_or_citations": True,
            "current_claims_require_current_evidence": bool(require_current_information),
            "record_publication_and_event_dates_separately_when_relevant": True,
            "report_conflicting_sources": True,
            "distinguish_fact_from_inference": True,
            "prefer_primary_sources": True,
            "browser_private_network_protections_must_remain_enabled": True,
            "browser_downloads_remain_disabled": True,
            "browser_actions_require_explicit_plan_permission": not bool(allow_browser_actions),
            "external_side_effects_require_policy_approval": True,
            "do_not_claim_future_monitoring_is_active_without_scheduler_evidence": True,
        },
        "stages": stages,
    }


def register(registry):
    registry.register(
        name="plan_research_browser_mission",
        description="Plan evidence-backed current research, source comparison, claim verification, bounded browser work, or a monitoring baseline with freshness and citation controls.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["research", "compare", "verify", "monitor", "browse"], "default": "research"},
                "depth": {"type": "string", "enum": ["quick", "standard", "deep"], "default": "standard"},
                "output": {"type": "string", "enum": ["answer", "brief", "report", "evidence_bundle", "document_package"], "default": "report"},
                "require_current_information": {"type": "boolean", "default": True},
                "require_citations": {"type": "boolean", "default": True},
                "max_sources": {"type": "integer", "minimum": 1, "maximum": 30, "default": 12},
                "allow_browser_actions": {"type": "boolean", "default": False}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_research_browser_plan,
        risk="read",
    )
