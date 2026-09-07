# DPN AI v10.0.0 — Marketplace Signing and Catalog Trust

## Purpose

Batch 13 extends the controlled capability marketplace with cryptographic publisher identity, signed catalog membership, and live ToolRegistry contract validation. The goal is to make a package's identity, publisher, declared risk, and catalog membership independently verifiable before any activation decision.

## Cryptographic model

`app/marketplace_trust_v10.py` uses Ed25519 public-key verification from the existing `cryptography` dependency. Private keys are never accepted or stored by the marketplace runtime. Trusted public keys are host-owned `PublisherKey` records and are resolved by `(publisher_id, key_id)`.

A package signature is detached from the code and covers the canonical normalized marketplace manifest. The manifest already contains the exact code SHA-256 digest, so a valid package signature binds publisher identity, package identity/version, source URI, code digest, declared tools, declared risk classes, and v10 compatibility bounds.

Revoked or unknown public keys fail closed. A package cannot substitute a different publisher identity for the signing key.

## Signed catalog/index

A `SignedCatalog` is schema-versioned and binds:

- publisher and key identity;
- generation and expiration timestamps;
- a bounded package/version index;
- exact normalized manifest SHA-256 values.

Catalog lifetime is capped at seven days, future timestamp skew is bounded, expired catalogs fail closed, duplicate package/version entries fail closed, and catalog entry count is capped at 1,024.

Package admission requires exact catalog membership: package ID, v10 checkpoint version, and manifest digest must all match one signed entry.

## Live ToolRegistry contract validation

Marketplace manifests declare the ToolRegistry tools they depend upon plus the risk classes they expect. `validate_live_tool_contract()` compares those declarations with the live host registry catalog.

Admission fails when:

- a declared tool is unavailable;
- registry metadata is malformed or duplicated;
- the live risk class exceeds the package's declared risk set.

Contract validation is explicitly non-authorizing (`execution_authorized=false`). It cannot invoke a tool or grant permissions.

## Staging boundary

`SignedMarketplaceStager.stage_verified()` requires all of the following before calling the existing non-executing `CapabilityMarketplace.stage()` path:

1. detached package signature verification;
2. current signed-catalog verification;
3. exact package/catalog membership;
4. live ToolRegistry contract verification;
5. the existing code digest, publisher allowlist, v10 compatibility, and CapabilityForge static-validation boundaries.

The result remains staged only. No imports, plugin registration, ToolRegistry invocation, or activation occur in this path.

## Approval boundary

Cryptographic trust is not execution authorization. Even a fully signed and cataloged package must still pass the existing destructive promotion/rollback ToolRegistry operations and `ApprovalSecurity`. Signatures establish provenance and integrity; they never bypass the approval system.

## Rotation and revocation

Host operators rotate keys by changing the host-owned public-key trust configuration. Revoked keys are rejected before signature verification is treated as trusted. The runtime intentionally does not provide a model-visible method for adding a trust root or unrevoking a key.

## Current checkpoint status

This checkpoint adds the cryptographic verifier, catalog verifier, signed non-executing staging bridge, live risk-contract validator, and regression coverage. Batch 13 release readiness remains pending exact-head CI/security verification and the dedicated marketplace benchmark/release gate.
