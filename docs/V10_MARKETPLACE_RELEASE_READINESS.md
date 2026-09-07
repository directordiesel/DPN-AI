# DPN AI v10.0.0 — Batch 13 Marketplace Release Readiness

Batch 13 uses an exact-test release manifest rather than aggregate test counts. Release readiness requires all five marketplace benchmark families to pass with success rate 1.0 and quality score 1.0.

Required families:

- `marketplace_package_integrity`
- `marketplace_publisher_signature`
- `marketplace_catalog_membership`
- `marketplace_tool_contract`
- `marketplace_approval_boundary`

The manifest is defined in `app/marketplace_release_audit_v10.py`. `app/marketplace_release_ci_v10.py` executes only those immutable pytest node IDs and fails closed when any required test is missing or fails. `.github/scripts/marketplace_release_readiness_v10.py` is the GitHub Actions entrypoint.

The approval-boundary family explicitly requires both plugin metadata proving promotion/rollback remain `risk="destructive"`, `gate="commands"` and a real promotion test proving CapabilityForge promotion preserves approval-boundary evidence. Cryptographic trust never grants execution authorization.

GitHub CI executes this gate on Ubuntu/Python 3.11 after the earlier v10 release gates. Batch 13 must not be marked complete until the exact PR head passes the full test matrix, DPN Security Gate v2, and this dedicated marketplace release gate.
