# DPN AI v10.0.0 — Advanced Layered Memory Foundation

## Purpose

Batch 8 extends the existing scoped key/value + semantic memory architecture instead of creating a second persistence engine. Durable memory continues through `MemoryService`, the existing database, and `SemanticMemory`; the v10 layer adds stronger scope isolation, typed memory classes, provenance, retention, conflict preservation, bounded working memory, and privacy-aware recall.

## Implemented layers

`AdvancedLayeredMemory` defines the approved v10 memory layer model:

- `working` — volatile bounded context with optional TTL;
- `conversation` — durable conversation-scoped memory;
- `project` — durable project-scoped memory;
- `organization` — durable organization-scoped memory;
- `user` — durable user-scoped memory;
- `procedural` — procedures/instructions stored in an explicitly resolved scope;
- `episodic` — events/experiences stored in an explicitly resolved scope;
- `semantic` — long-term semantic knowledge, defaulting away from conversation scope unless explicitly requested.

The persistent layers reuse the existing `MemoryService.remember()` and semantic index. No new database is introduced.

## Scope isolation

`MemoryScope` now includes `organization` and `user` in addition to `global`, `project`, and `conversation`. Each non-global scope requires its matching identifier. Recall constructs visibility only from identifiers explicitly present in the active `MemoryContext`:

`global → organization → user → project → conversation`.

A user or organization namespace is therefore not included merely because it exists in storage.

## Provenance and knowledge classes

Every v10 memory write requires typed provenance containing:

- source type;
- stable source identifier;
- evidence identifiers where applicable;
- confidence in `[0, 1]`;
- authority in `[0, 1]`.

Memories are classified as `observation`, `fact`, `derived`, `inference`, `procedure`, or `episode`. `derived` and `inference` writes require evidence IDs before any mutation occurs. This prevents low-grounding model output from silently becoming trusted durable knowledge.

## Version preservation and conflicts

The v10 runtime does not overwrite a logical memory merely because a later value uses the same key. Persistent storage keys include a deterministic content hash, preserving distinct versions. Existing versions for the same layer/scope/logical key are inspected before a write. A differing version is admitted as an explicit conflict and the write receipt lists the conflicting memory IDs.

Recall groups differing active versions and marks all returned members of that logical key as conflicting. The runtime does not silently select one as truth.

## Retention and working memory

Working memory is in-process, bounded, deterministically evicted by oldest creation time, and can expire through TTL. Persistent memory may also carry TTL metadata; expired entries are excluded from version checks and recall.

## Sensitive writes

Sensitive persistent writes require an externally injected approval guard. If no guard exists, the operation fails closed. The caller cannot self-assert an approval boolean in the memory request.

No destructive forget/supersede API is introduced in this checkpoint. Destructive or cross-scope mutation will remain approval-gated when added later in Batch 8.

## Recall ranking

Persistent recall reuses semantic similarity from the existing semantic store, then combines it with provenance confidence, authority, and freshness. Working memory uses bounded lexical overlap plus provenance confidence/authority. Results are limited and deterministically sorted.

## Fail-closed behavior

Persistent writes are blocked if existing versions cannot be inspected. Persistent recall is blocked if the semantic store fails. Scope mismatches, missing identifiers, invalid provenance, invalid TTL, duplicate/empty evidence IDs, and unsupported layer/scope combinations are rejected before mutation.

## Current integration boundary

This checkpoint establishes the trusted memory substrate. It does not yet:

- ingest Deep Research evidence automatically;
- promote mission checkpoints into episodic memory;
- implement controlled supersession/forgetting;
- compact or summarize long histories;
- expose public tools/API routes;
- provide benchmark/readiness scoring for memory quality.

Those are subsequent Batch 8 integration checkpoints and must reuse this provenance/scope/conflict contract rather than bypassing it.
