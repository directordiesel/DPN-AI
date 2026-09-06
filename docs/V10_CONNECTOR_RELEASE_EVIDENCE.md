# DPN AI v10.0.0 — Connector Release Evidence Gate

## Purpose

Batch 6 now exposes a deterministic release-evidence surface for the DPN Connector Protocol ecosystem. The release gate is intentionally stricter than ordinary connector health reporting: a connector can be healthy while still violating the v10 security contract.

The `dpn_connector_ecosystem_release_evidence` tool performs a read-only contract inspection plus operational readiness aggregation. It executes no connector actions, decrypts no credentials, and returns no provider response bodies.

## Contract gate

Every advertised `create`, `update`, or `delete` capability must declare `approval_required=True`. Any mutating capability that does not explicitly require approval is reported as `mutation_without_explicit_approval`, sets `contract_ready=false`, and prevents `release_ready` from becoming true.

This check is derived directly from live connector manifests rather than from tool names or provider assumptions. The gate therefore applies consistently across HTTP, MCP, SQL, and future DPN Connector Protocol transports.

## Operational gate

Operational readiness remains fail-closed. A connector is operationally ready only when it is configured, enabled, and reports `healthy` or `degraded` through its transport adapter. Disabled, unconfigured, or unavailable connectors remain blocked with bounded reason codes.

`release_ready=true` requires both:

1. `contract_ready=true` — at least one connector exists and there are zero unapproved mutating capabilities.
2. `operational_ready=true` — every discovered connector passes the existing operational readiness rules.

The report includes connector/transport counts, the number of approval-protected mutating capabilities, bounded contract violations, and the existing blocked operational reason summary.

## Security properties

- No connector action is executed while generating evidence.
- No credential value is decrypted or returned.
- No provider body or provider exception text is returned.
- Duplicate connector identities continue to fail closed before evidence is produced.
- Mutating capabilities are evaluated from typed protocol actions, not string heuristics.
- An empty connector ecosystem cannot be release ready.
- The tool is registered under the `connectors` gate with `risk="read"`; it has no authority to grant, consume, or bypass approval.

## Verification coverage

`tests/test_dpn_connector_ecosystem_v10.py` verifies both the passing contract case and the fail-closed case where a destructive `delete` capability is advertised without approval. The fake adapters reject execution, proving release evidence remains inventory/health-only.

`tests/test_dpn_connector_approval_bridge_v10.py` pins the public tool registration to the connector gate and read-only risk classification.

## Batch 6 release use

Before Batch 6 is considered merge-ready, the exact branch head must pass the repository CI matrix, DPN Security Gate v2, and Runtime & Recovery Assurance. The release-evidence contract is an additional application-level gate; it does not replace CI or human approval requirements for destructive actions.
