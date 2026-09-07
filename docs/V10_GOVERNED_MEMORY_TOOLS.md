# DPN AI v10 Governed Layered Memory Tools

This checkpoint exposes the Batch 8 layered-memory runtime through the existing plugin/ToolRegistry architecture instead of creating a parallel API or direct database surface.

## Registered tools

- `dpn_memory_recall` — read-only scoped recall across allowed v10 layers.
- `dpn_memory_remember` — bounded non-sensitive memory creation through `AdvancedLayeredMemory` validation.
- `dpn_memory_lineage_inspect` — read-only compaction/recovery evidence for one exact scope.
- `dpn_memory_supersede` — evidence-backed, non-destructive replacement plus immutable lineage receipt.

## Security boundaries

The tool surface does **not** expose raw SQL, semantic-store mutation, deletion, garbage collection, direct compaction mutation, `approval_granted`, or a caller-controlled `sensitive` flag. Sensitive durable memory continues to require higher-trust internal integration with an externally injected `AdvancedLayeredMemory` approval guard.

`dpn_memory_supersede` is classified as destructive/consequential for authorization purposes even though it preserves old records. `ToolPermissionRuntime` forces it to `ASK_EVERY_TIME` with `approval_required=true` even when the broader policy is Always Allow/autonomous. This protects the preferred long-term knowledge view from silent autonomous rewrites.

Supersession itself remains non-destructive: prior records remain stored and the preference decision is represented by an evidence-backed procedural lineage receipt.

Lineage inspection requires an explicit scope plus the identifier required by that scope. The service derives the namespace through `ScopedMemory`; callers cannot pass an arbitrary raw namespace string.

## Integration

`plugins/layered_memory_v10.py` constructs `GovernedMemoryToolService` from the real `ToolRegistry.db` and `ToolRegistry.semantic` instances. All persistent writes therefore continue through the existing `MemoryService` and semantic persistence path.

## Verification focus

`tests/test_memory_tools_v10.py` verifies the exact bounded tool catalog, absence of approval/sensitive/raw-storage bypass parameters, forced human approval for durable supersession, scope-identity validation, and evidence requirements for supersession.
