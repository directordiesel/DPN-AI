# DPN AI v10 Memory Compaction & Recovery

## Purpose

Batch 8 keeps durable memory history immutable. Compaction therefore means deriving a smaller, safer read view rather than deleting historical evidence.

`app/memory_compaction_v10.py` provides `MemoryCompactionService`, which inspects one exact durable memory scope and returns a deterministic compaction/recovery report.

## Safety model

The service performs no destructive mutation. It never deletes semantic items, key/value rows, supersession receipts, or prior conflicting versions.

Exact duplicate records are grouped by scope, layer, logical key, and content hash. The lexicographically smallest durable memory ID becomes the canonical read identity for that duplicate group, while every stored duplicate remains intact.

Supersession is honored only when its procedural receipt is structurally valid and all referenced memories exist in the same exact scope/layer/logical-key lineage. A valid receipt can remove an older canonical memory from the preferred read view, but it cannot delete that memory.

Malformed, dangling, cross-lineage, or cyclic supersession evidence is fail-closed. Such evidence is ignored for preference selection and surfaced as `recovery_required=true` with explicit receipt or memory IDs.

## Recovery findings

The report exposes:

- `invalid_receipt_ids`
- `dangling_receipt_ids`
- `cycle_memory_ids`
- `duplicate_groups`
- `superseded_memory_ids`
- `preferred_memory_ids`
- `recovery_required`

This lets future governed APIs and benchmark gates distinguish a clean compacted view from memory state that requires human or trusted-system repair.

## Boundaries

This checkpoint does not add deletion, garbage collection, automatic conflict resolution, or repair writes. Those would be higher-risk mutations and require a separately governed workflow with explicit approval boundaries.

Compaction is intentionally read-only and deterministic so a storage inspection failure cannot be mistaken for a healthy memory state.
