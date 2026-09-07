# DPN AI v10.0.0 — Trusted Proactive Sources and Dispatch

## Purpose

Batch 11 extends the proactive condition foundation with two production boundaries: host-owned observation provenance/freshness and idempotent proposal dispatch that re-enters the existing ToolRegistry/ApprovalSecurity path.

## Trusted condition sources

`app/proactive_sources_v10.py` defines host-owned `SourceContract` registrations and `ObservationEvidence` receipts. Model-visible tools may collect registered sources but cannot register a source, change its freshness window, or mark arbitrary caller data as trusted.

Each observation records:

- host-defined source ID;
- observed/collected/expiry timestamps;
- canonical finite JSON value;
- SHA-256 source digest;
- host-defined `trusted_for_dispatch` policy.

Collection fails closed for unknown sources, stale/future timestamps, invalid clocks, duplicate source registration, and non-finite/non-JSON values.

The first integrated host source is `system.pending_approvals`, derived directly from the local database approval inbox with a 30-second freshness contract.

## Proposal binding

`ProactiveConditionEngine` binds proposals to the trusted source ID, source digest, and a SHA-256 observation digest. Caller-supplied `evaluate_proactive_condition` observations remain explicitly `manual` and `trusted_source=false`, so they can inform/report but cannot enter automated dispatch.

## Approval-preserving dispatch

`app/proactive_dispatch_v10.py` implements `ProactiveProposalDispatcher`. Before the first dispatch it verifies:

1. the proposal did not self-authorize execution;
2. both proposal and evidence are trusted;
3. proposal/evidence source IDs and digests match;
4. evidence is still fresh at dispatch time;
5. the target tool is still registered;
6. current tool risk/gate metadata is unchanged from evaluation.

The dispatcher then calls **only** `ToolRegistry.execute(tool_name, arguments, permissions)`. That existing method delegates to `ApprovalSecurity`, which applies current authorization and creates an approval request when required. The proactive layer never calls `_invoke` directly.

## Idempotent receipts

Every first dispatch attempt creates an atomic persistent receipt keyed by `proposal_id`. Replays return the existing receipt and do not call ToolRegistry again. Approval-pending receipts therefore cannot generate duplicate approval requests.

Corrupt or schema-invalid receipt state blocks dispatch rather than resetting history.

## Plugin integration

`plugins/proactive_intelligence_v10.py` exposes trusted-source evaluation but intentionally does **not** expose a model-visible dispatch tool. Matching trusted proposals are cached host-side. Internal runtimes may invoke `registry.dispatch_cached_proactive_proposal_v10(proposal_id, host_permissions)` with permissions resolved by the host runtime.

This keeps the condition evaluator non-executing while creating a real integration point for later mission/connector operations.

## Security invariants

- no model-supplied trust bit;
- no model-visible source registration;
- no direct `_invoke` path from proactive dispatch;
- no approval bypass;
- no replay after first dispatch attempt;
- no dispatch on stale evidence;
- no dispatch after risk/gate drift;
- destructive/external/execute tools remain governed by the existing approval system.
