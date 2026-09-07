# DPN AI v10 — Deep Research Memory Bridge

## Purpose

`DeepResearchMemoryBridge` connects the completed v10 Deep Research trust chain to the Advanced Layered Memory architecture without allowing model output to become durable knowledge directly.

The bridge only promotes a research mission after the mission is release-ready, citation validation succeeded, every graph claim has a deterministic fact-check result, and every promoted claim is `verified`.

## Trust boundary

The bridge does not accept free-form evidence identifiers from the writer or extractor as memory provenance. Supporting evidence IDs are re-read from the trusted `EvidenceGraph`, and each referenced evidence node must still exist before any memory mutation begins.

The fact-check set must exactly cover the live graph claim set. Missing claims, invented claim IDs, duplicate claim IDs, disputed claims, stale/unsupported claims, invalid confidence, missing evidence, or invalid citations fail closed before memory writes.

## Semantic promotion

Each verified claim is promoted to the `semantic` layer as a `fact` with:

- a deterministic mission/claim key;
- the normalized verified claim text;
- Deep Research mission provenance;
- supporting Evidence Graph IDs;
- claim confidence;
- evidence-derived authority;
- the caller's explicit memory scope context.

Existing `AdvancedLayeredMemory` version preservation, scope isolation, conflict detection, retention, and sensitive-write approval policy remain authoritative.

## Episodic promotion

The grounded final report is stored as an `episodic` memory only after all semantic claim promotions succeed. This prevents a mission episode from being recorded as fully learned while one of its semantic facts failed to persist.

If semantic persistence fails partway through, the bridge reports the exact partial receipt and does not claim atomic rollback because the memory service intentionally has no destructive rollback API. Re-running the bridge is safe because the underlying layered memory IDs and physical keys are deterministic/idempotent for identical content.

## Sensitive research

The bridge forwards the `sensitive` flag to every memory write. It does not contain an approval boolean or bypass. Sensitive durable promotion therefore still requires the externally injected `AdvancedLayeredMemory` approval guard.

## Readiness contribution

This checkpoint establishes a real end-to-end path:

`Deep Research evidence -> deterministic fact checking -> release-ready mission -> governed semantic facts + episodic mission memory`

It intentionally does not yet implement destructive forgetting, supersession, automated compaction, or low-confidence inference promotion. Those remain later Batch 8 work and must preserve fail-closed approval boundaries.
