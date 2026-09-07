# DPN AI v10 — Batch 8 Layered Memory Security Audit

## Scope

This audit covers the Batch 8 advanced layered memory architecture, Deep Research and long-horizon mission promotion bridges, supersession lineage, compaction/recovery analysis, governed tool exposure, benchmark/readiness logic, and CI release-evidence integration.

## Security conclusions

### Scope and tenant isolation

Non-global organization, user, project, and conversation identifiers are routing inputs only. Model-visible arguments do not establish authority. Governed memory operations require a host-injected scope authorizer before non-global storage inspection or mutation. Existing user/project namespace isolation is preserved by `MemoryContext` and `ScopedMemory`.

### Provenance and semantic truth

Persistent v10 memory carries typed provenance. Derived and inferred knowledge requires evidence IDs. Deep Research promotion accepts only deterministic release-ready, citation-valid, verified claims and re-derives provenance from the trusted Evidence Graph rather than trusting model-authored citation identities. Long-horizon mission history is promoted only as episodic evidence after checkpoint integrity, persisted-step agreement, deterministic review, and security review checks.

### Conflict handling

Conflicting persistent versions are preserved and surfaced. The runtime does not silently select one conflicting fact as truth. Supersession is a distinct governed operation that requires evidence, equal-or-stronger authority, exact scope/layer/logical-key lineage, and a durable procedural receipt.

### Non-destructive lifecycle

Batch 8 adds no automatic persistent delete, destructive compaction, or in-place historical rewrite path. Compaction is a read-only derived view. Superseded and duplicate records remain auditable. Recovery detects malformed receipts, dangling references, cross-lineage references, and cycles instead of silently repairing or discarding them.

### Approval boundaries

Sensitive persistent memory uses the externally injected approval guard. The model-visible memory tools expose no `approval_granted`, raw SQL, raw semantic-store mutation, delete, or sensitive-bypass parameter. `dpn_memory_supersede` is forced behind explicit human approval even when a broader policy would otherwise allow execution. Dedicated memory/connector approval boundaries may annotate or narrow an approval-required decision but cannot override a hard DENY.

### Fail-closed storage behavior

Persistent writes inspect existing versions before mutation. If version inspection fails, the write is refused. Lineage operations fail closed on storage inspection failure. If a non-transactional lineage receipt write fails after a replacement was already persisted, the operation reports partial persistence explicitly rather than claiming rollback.

### Benchmark and release evidence

Eight critical memory families are required: scope isolation, provenance integrity, conflict preservation, supersession lineage, recovery detection, retention bounds, trusted promotion, and tool authorization. Batch 8 requires 1.0 success and 1.0 quality for every family. The release audit maps those families to exact pytest node IDs and accepts readiness only from trusted executed-test evidence.

The dedicated CI harness runs the exact manifest test IDs, refuses caller-substituted test identities, and emits ready evidence only if pytest succeeds and the strict benchmark audit returns ready. Repository-wide CI, DPN Security Gate v2, and Runtime & Recovery Assurance remain independent exact-head requirements.

## Explicitly absent capabilities

The Batch 8 surface intentionally does not provide:

- automatic durable-memory deletion;
- destructive compaction;
- silent conflict resolution;
- caller-supplied approval assertions;
- model-controlled provenance identity;
- model-controlled citation identity for semantic promotion;
- arbitrary raw SQL against the memory store;
- cross-scope memory reads based only on a supplied namespace ID;
- automatic semantic promotion from successful mission prose.

## Release decision

Batch 8 can be marked merge-ready only after the final exact head passes:

1. the full Ubuntu/Windows Python 3.11/3.12 CI matrix;
2. the dedicated memory release-readiness CI step with all eight benchmark families ready;
3. DPN Security Gate v2;
4. Runtime & Recovery Assurance;
5. expected Windows Desktop Package outcome;
6. no unresolved destructive/high-risk approval requirement.

The audit itself does not merge PR #93 or perform destructive memory operations.
