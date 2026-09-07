# DPN AI v10.0.0 — Controlled Capability Marketplace

Batch 13 extends the existing `CapabilityForge` instead of replacing the trusted local plugin architecture.

## Governance model

Marketplace packages are never executed during inspection or validation. A package must provide a bounded v10 manifest with an exact SHA-256 code digest, a host-trusted publisher ID, an approved source URI scheme, declared tool names, requested risk classes, and a `10.0.x` checkpoint version.

The marketplace records atomic, schema-versioned evidence under the DPN data directory. Evidence binds package ID, version, publisher, source, manifest digest, code digest, staged timestamp, validation digest, promotion timestamp, and rollback lineage.

## Lifecycle

1. **Inspect** — verifies manifest structure, v10 compatibility, trusted publisher membership, and exact source digest. Code is not imported or executed.
2. **Stage** — delegates to the existing `CapabilityForge.stage()` only after marketplace trust checks pass. Staging returns `execution_authorized=false`.
3. **Validate** — delegates to `CapabilityForge.validate()`, then independently proves the staged bytes still match marketplace evidence.
4. **Promote** — revalidates immediately before activation and delegates to `CapabilityForge.promote()`. The plugin tool is registered as `risk="destructive"` with `gate="commands"`, so normal ToolRegistry/ApprovalSecurity policy remains authoritative.
5. **Rollback** — delegates to the existing backup-preserving `CapabilityForge.rollback()` and records rollback lineage. The tool is also destructive/commands-gated.

## Security boundaries

- no package code execution during marketplace inspection or staging;
- no automatic activation;
- no direct ToolRegistry `_invoke()` path;
- promotion and rollback remain normal high-risk ToolRegistry operations;
- publisher trust is host-owned and can be revoked; persisted packages fail closed after revocation;
- source or staged-byte drift invalidates promotion;
- v11/other-major manifests are rejected because the approved program remains v10.0.0;
- symlink, source-size, AST validation, backup, and atomic-write protections remain owned by the existing CapabilityForge.

## First checkpoint limitations

This checkpoint implements trusted-publisher allowlisting plus cryptographic content/manifest digests. Public-key package signatures and remote catalog synchronization are intentionally not claimed yet; they require a host-managed signing-key trust store and additional release evidence.
