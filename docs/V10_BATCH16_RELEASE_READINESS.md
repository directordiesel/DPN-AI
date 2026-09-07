# DPN AI v10.0.0 — Batch 16 Security + Regression Release Readiness

Batch 16 converts the security-hardening work into an executable, fail-closed release gate. Readiness is evidence-only and never authorizes execution, deployment, merge, connector mutation, capability activation, or approval.

## Mandatory release families

The Batch 16 manifest is fixed in `app/security_regression_release_v10.py`. The dedicated gate executes the exact pytest node IDs for seven mandatory families:

1. benchmark evidence integrity;
2. repository path containment;
3. CI terminal-state integrity;
4. model/provider benchmark provenance;
5. connector risk/approval contract integrity;
6. approval payload binding;
7. approval exact-argument reauthorization.

An omitted family, unexpected caller-supplied family, failed test, malformed evidence, or attempted authorization claim blocks readiness.

## Approval payload hardening

Deferred tool arguments remain encrypted in `SecretVault`. The SQLite approval record retains only a sanitized preview plus an internal SHA-256 binding over the exact tool name, effective risk, gate, and normalized deferred arguments. Before a previously approved action can execute, DPN AI:

- verifies the approval is still active and not expired;
- requires the encrypted payload to parse as an object;
- recomputes and verifies the stored payload/tool/risk/gate binding;
- re-runs current permission policy over the exact decrypted arguments;
- rejects live risk drift or a current hard deny;
- atomically claims the approval for single-use execution;
- destroys the encrypted payload on every terminal path.

Legacy or tampered approvals that lack the v10 binding cannot be executed and fail closed.

## CI integration

`.github/workflows/ci.yml` runs `.github/scripts/security_regression_release_readiness_v10.py` on Ubuntu/Python 3.11 after the Batch 8–15 gates. The harness invokes only the immutable Batch 16 manifest and surfaces bounded pytest diagnostics on failure.

A green ordinary test suite is necessary but is not sufficient for Batch 16 readiness; the dedicated release gate must also pass on the exact PR head.
