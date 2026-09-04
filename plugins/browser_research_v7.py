from __future__ import annotations

from typing import Any


MODES = {"research", "compare", "verify", "browse", "monitor"}
DEPTHS = {"quick", "standard", "deep"}
OUTPUTS = {"answer", "brief", "report", "evidence_bundle", "document_package"}


def _normalize(value: str, allowed: set[str], fallback: str) -> str:
    normalized = str(value or fallback).strip().lower()
    return normalized if normalized in allowed else fallback


def build_browser_research_v7_plan(
    objective: str,
    mode: str = "research",
    depth: str = "standard",
    output: str = "report",
    require_current_information: bool = True,
    require_citations: bool = True,
    max_sources: int = 16,
    max_pages_per_source: int = 6,
    allow_browser_actions: bool = False,
    allow_downloads: bool = False,
) -> dict[str, Any]:
    objective = str(objective or "").strip()
    mode = _normalize(mode, MODES, "research")
    depth = _normalize(depth, DEPTHS, "standard")
    output = _normalize(output, OUTPUTS, "report")
    source_cap = max(1, min(int(max_sources), 40))
    page_cap = max(1, min(int(max_pages_per_source), 20))
    target_sources = {"quick": min(source_cap, 5), "standard": min(source_cap, 12), "deep": min(source_cap, 30)}[depth]

    stages: list[dict[str, Any]] = [
        {"id": "frame", "goal": "Turn the objective into explicit research questions, scope, freshness requirements, exclusions, and acceptance criteria."},
        {"id": "source_strategy", "goal": "Prioritize primary/official sources, then authoritative direct sources, then strong independent secondary sources; use community evidence only when relevant to the question."},
        {"id": "discover", "goal": "Discover candidate sources using available search, browser, connector, and local knowledge capabilities without inventing access or results."},
        {"id": "retrieve", "goal": "Retrieve bounded source content while recording canonical URL, title, publisher, publication/update date, retrieval time, and relevant evidence spans."},
        {"id": "evaluate", "goal": "Score authority, recency, directness, independence, corroboration, conflicts, and limitations for each source."},
        {"id": "claim_ledger", "goal": "Build a claim-to-source ledger so every material factual claim can be traced to one or more captured sources."},
    ]
    if mode in {"compare", "verify"}:
        stages.append({"id": "cross_check", "goal": "Cross-check important claims across independent evidence and surface contradictions instead of averaging them away."})
    if mode == "browse":
        stages.append({"id": "browser_workflow", "goal": "Use bounded browser navigation only when interaction is needed; record navigation steps, final URLs, screenshots/evidence, and approval boundaries."})
    if mode == "monitor":
        stages.append({"id": "baseline", "goal": "Capture a comparison baseline and change criteria; scheduling/recurrence must be delegated to the scheduler and must never be implied by this plan alone."})
    stages.extend([
        {"id": "synthesize", "goal": "Synthesize only from the evidence ledger, separating sourced facts, calculations, inference, uncertainty, and unresolved contradictions."},
        {"id": "citation_audit", "goal": "Verify citations resolve to captured sources and support the exact nearby claims; reject fabricated or decorative citations."},
        {"id": "freshness_audit", "goal": "For time-sensitive claims, compare publication date, event date, and retrieval date and prefer evidence matching the requested time window."},
        {"id": "deliver", "goal": "Return the requested artifact with findings, citations/evidence, dates, confidence, limitations, contradictions, and exact generated paths when artifacts are created."},
    ])

    return {
        "ok": bool(objective),
        "objective": objective,
        "mode": mode,
        "depth": depth,
        "output": output,
        "limits": {"max_sources": source_cap, "target_sources": target_sources, "max_pages_per_source": page_cap},
        "required_capabilities": ["research", "browser", "source_evaluation", "citation_audit", "freshness_audit", "provenance", "evidence_validation"],
        "quality_gates": [
            "objective_answered",
            "captured_source_ledger_present",
            "material_claims_traceable",
            "authority_recency_directness_evaluated",
            "contradictions_reported",
            "fact_inference_uncertainty_separated",
            "citations_resolve_to_captured_sources" if require_citations else "citation_requirement_disabled_explicitly",
            "freshness_verified" if require_current_information else "freshness_requirement_disabled_explicitly",
        ],
        "execution_policy": {
            "never_invent_sources_or_citations": True,
            "current_claims_require_matching_current_evidence": bool(require_current_information),
            "record_publication_event_and_retrieval_dates_separately": True,
            "prefer_primary_sources": True,
            "report_conflicting_sources": True,
            "distinguish_fact_inference_and_unknown": True,
            "browser_private_network_protections_must_remain_enabled": True,
            "browser_actions_allowed": bool(allow_browser_actions),
            "downloads_allowed": bool(allow_downloads),
            "downloads_require_existing_security_policy": True,
            "external_side_effects_require_approval": True,
            "credentials_must_not_be_logged_or_persisted_in_evidence": True,
            "respect_source_access_controls_and_robots_policy": True,
            "do_not_claim_future_monitoring_without_scheduler_evidence": True,
            "bounded_navigation_required": True,
        },
        "stages": stages,
    }


def evaluate_research_evidence_v7(
    evidence: dict[str, Any] | None,
    require_current_information: bool = True,
    require_citations: bool = True,
) -> dict[str, Any]:
    evidence = dict(evidence or {})
    sources = evidence.get("sources") or []
    claims = evidence.get("claims") or []
    contradictions = evidence.get("contradictions")
    freshness_checked = bool(evidence.get("freshness_checked"))
    citation_audited = bool(evidence.get("citation_audited"))

    source_ids = {str(item.get("id")) for item in sources if isinstance(item, dict) and item.get("id")}
    valid_sources = [
        item for item in sources
        if isinstance(item, dict)
        and item.get("id")
        and item.get("url")
        and item.get("title")
        and item.get("retrieved_at")
    ]
    material_claims = [item for item in claims if isinstance(item, dict) and item.get("material", True)]
    unsupported_claims: list[str] = []
    for claim in material_claims:
        refs = {str(ref) for ref in (claim.get("source_ids") or [])}
        if not refs or not refs.issubset(source_ids):
            unsupported_claims.append(str(claim.get("id") or claim.get("claim") or "unknown"))

    failures: list[str] = []
    if not valid_sources:
        failures.append("no_valid_captured_sources")
    if unsupported_claims:
        failures.append("material_claims_without_valid_source_links")
    if require_current_information and not freshness_checked:
        failures.append("freshness_not_verified")
    if require_citations and not citation_audited:
        failures.append("citations_not_audited")
    if contradictions is None:
        failures.append("contradiction_review_missing")
    if evidence.get("fabricated_source_detected"):
        failures.append("fabricated_source_detected")

    return {
        "ok": not failures,
        "failures": failures,
        "source_count": len(valid_sources),
        "material_claim_count": len(material_claims),
        "unsupported_claims": unsupported_claims,
        "freshness_checked": freshness_checked,
        "citation_audited": citation_audited,
        "completion_allowed": not failures,
    }


def register(registry) -> None:
    registry.register(
        name="plan_browser_research_v7",
        description="Plan evidence-backed Browser & Research v7 work with bounded navigation, source-quality evaluation, freshness controls, claim-source provenance, contradiction handling, and citation audits.",
        parameters={
            "type": "object",
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": sorted(MODES), "default": "research"},
                "depth": {"type": "string", "enum": sorted(DEPTHS), "default": "standard"},
                "output": {"type": "string", "enum": sorted(OUTPUTS), "default": "report"},
                "require_current_information": {"type": "boolean", "default": True},
                "require_citations": {"type": "boolean", "default": True},
                "max_sources": {"type": "integer", "minimum": 1, "maximum": 40, "default": 16},
                "max_pages_per_source": {"type": "integer", "minimum": 1, "maximum": 20, "default": 6},
                "allow_browser_actions": {"type": "boolean", "default": False},
                "allow_downloads": {"type": "boolean", "default": False}
            },
            "required": ["objective"],
            "additionalProperties": False
        },
        function=build_browser_research_v7_plan,
        risk="read",
    )
    registry.register(
        name="evaluate_research_evidence_v7",
        description="Evaluate whether Browser & Research v7 has enough source, claim-link, freshness, contradiction, and citation evidence to make a completion claim.",
        parameters={
            "type": "object",
            "properties": {
                "evidence": {"type": "object"},
                "require_current_information": {"type": "boolean", "default": True},
                "require_citations": {"type": "boolean", "default": True}
            },
            "required": ["evidence"],
            "additionalProperties": False
        },
        function=evaluate_research_evidence_v7,
        risk="read",
    )
