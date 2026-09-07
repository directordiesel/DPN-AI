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

### Host-authorized scope identity

Organization, user, project, and conversation identifiers may appear in model-visible tool arguments for routing, but they are **not authority**. `GovernedMemoryToolService` now requires a host-injected `scope_authorizer(scope, MemoryContext)` before any non-global scope is used. If the host has not installed an authorizer, non-global memory access fails closed even when a caller provides a syntactically valid identifier.

The plugin reads an optional `registry.memory_scope_authorizer` callback. This keeps identity/tenant authorization outside model-controlled arguments and lets the real application/session layer decide whether the active principal may access the requested scope. A denied or failing authorizer blocks the operation before storage inspection, recall, persistence, or supersession.

Global memory remains available without a scope authorizer because it carries no tenant/user/project identifier. A host that needs stricter global policy can still restrict the tool itself through `ToolPermissionRuntime`.

## Integration

`plugins/layered_memory_v10.py` constructs `GovernedMemoryToolService` from the real `ToolRegistry.db` and `ToolRegistry.semantic` instances and forwards the optional host scope authorizer. All persistent writes therefore continue through the existing `MemoryService` and semantic persistence path.

This checkpoint deliberately consolidated onto the existing `memory_tool_service_v10.py` + `plugins/layered_memory_v10.py` architecture. A temporary parallel facade created during implementation was removed before completion so DPN AI has one governed memory tool surface rather than competing implementations.

## Verification focus

`tests/test_memory_tools_v10.py` verifies the exact bounded tool catalog, absence of approval/sensitive/raw-storage bypass parameters, forced human approval for durable supersession, fail-closed non-global access without host authorization, exact scope/context delivery to an injected authorizer, required scope identity, and evidence requirements for supersession.

## Remaining Batch 8 work

After exact-head CI/security/recovery verification, Batch 8 still requires dedicated memory-quality/readiness benchmarks plus a final security/release-readiness audit before PR #93 can be considered complete.
