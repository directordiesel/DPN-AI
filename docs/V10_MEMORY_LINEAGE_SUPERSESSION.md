# DPN AI v10.0.0 — Governed Memory Promotion and Supersession

Batch 8 introduces an immutable lineage model for correcting durable memory without destructive overwrite.

## Design

`MemoryLineageService` accepts an evidence-backed replacement memory plus one or more exact memory IDs to supersede. The service verifies that every target belongs to the same scope, layer, and logical key as the replacement before any write occurs.

The replacement must carry evidence IDs and cannot have lower authority than the strongest superseded version. Working memory is excluded because supersession is a durable lineage operation.

## Non-destructive behavior

Supersession never deletes or edits prior memory versions. The replacement is written through `AdvancedLayeredMemory`, preserving the existing conflict/version model. After the replacement succeeds, a procedural derived-memory receipt is written containing:

- replacement memory ID;
- superseded memory IDs;
- scope/layer/logical-key identity;
- bounded human-readable reason;
- evidence lineage covering the replacement and superseded versions.

This means an operator can recover the complete history and audit why a newer version was preferred.

## Fail-closed controls

The service rejects requests when:

- the reason is missing or oversized;
- target IDs are missing, duplicated, or exceed bounds;
- any target is outside the exact memory lineage;
- replacement content is identical to a target;
- replacement provenance has no evidence IDs;
- replacement authority is weaker than the strongest target;
- existing memory versions cannot be inspected;
- sensitive persistence is not approved by the injected `AdvancedLayeredMemory` approval guard.

A lineage-receipt failure after a successful replacement is reported as partial persistence; the service never claims rollback occurred when it did not.

## Security boundary

This checkpoint does **not** add destructive forgetting, deletion, or in-place mutation. It also does not allow a caller to declare approval. Sensitive writes continue through the existing external approval guard.

The design intentionally preserves conflicting historical versions until later compaction/recovery policy can safely reason over explicit lineage receipts.
