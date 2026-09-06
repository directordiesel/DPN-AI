# DPN AI v10.0.0 — Evidence-Grounded Deep Research Writer

## Purpose

`app/deep_research_writer_v10.py` is the synthesis boundary for Batch 7 Deep Research. It converts an already-admitted Evidence Graph into a final research report only when every claim is deterministically verified and citation-grounded.

The writer/provider is treated as untrusted. It cannot introduce source identity, evidence identity, claim identity, or citation provenance.

## Fail-closed synthesis contract

Before any model/provider writer is invoked, DPN AI independently runs the deterministic fact checker and conflict detector over the live Evidence Graph.

Final synthesis is blocked when any claim is:

- disputed;
- unsupported;
- stale; or
- involved in an unresolved detected conflict.

When blocked, the provider writer is not called. The result contains bounded `blocked_claims` and `unresolved_conflicts` evidence so callers can surface what must be resolved without presenting disputed material as a completed report.

## Trusted writer input

The provider receives only verified claims. Each claim payload contains:

- the admitted claim ID and text;
- deterministic confidence;
- supporting evidence already attached to the claim;
- source/evidence identity, locator, excerpt, and workstream provenance taken from the live graph.

Refuting, unsupported, stale, unknown, or unattached evidence is never promoted into the synthesis payload.

## Untrusted writer output validation

The provider returns bounded structured sections. Every section must contain:

- a title;
- prose text;
- one or more unique claim IDs.

Every referenced claim ID must belong to the verified claim set supplied to the writer. Unknown or unverified claim references reject synthesis. Every verified claim must be covered by at least one section.

Section count and section length are bounded. Malformed output fails closed.

## Citation authority

The provider does not author authoritative citations. After section validation, DPN AI derives citations itself from the graph's trusted claim-to-supporting-evidence relationships and revalidates them through `CitationValidator`.

The final rendered report appends deterministic markers such as:

`[cite:<claim-id>:<evidence-id>]`

A section without accepted trusted citations is rejected.

## Conflict preservation

The writer never silently resolves conflicting evidence. If qualified supporting and refuting evidence coexist, synthesis returns `status="blocked"`, an empty final report, and explicit unresolved conflict details. This preserves disagreement for later research or human review instead of allowing fluent prose to hide uncertainty.

## Security properties

This component:

- performs no destructive action;
- performs no database or connector write;
- grants no approval;
- does not broaden browser/network permissions;
- does not allow provider-authored provenance;
- does not allow provider-authored trusted citations;
- does not synthesize stale, unsupported, or disputed claims.

## Regression coverage

`tests/test_deep_research_writer_v10.py` verifies:

- verified synthesis with trusted citation rendering;
- disputed-claim blocking before provider invocation;
- stale-claim blocking;
- rejection of invented claim IDs;
- required coverage of all verified claims;
- rejection of ungrounded sections;
- writer return-type bounds;
- section-count bounds; and
- section-length bounds.

## Batch 7 integration state

The Batch 7 path now reaches:

`WEB / DOCUMENTS / DATA -> Evidence Graph -> claim extraction -> fact checking -> conflict detection -> citation validation -> readiness -> evidence-grounded writer`

Remaining Batch 7 work is end-to-end orchestration/readiness evidence across all workstreams, integration/security audit, exact-head CI verification, and release-readiness consolidation before merge.
