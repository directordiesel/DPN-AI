# DPN AI v10.0.0 — Connector Operational Readiness

Batch 6 now exposes a deterministic connector operational-readiness report through `dpn_connector_ecosystem_readiness`.

## Purpose

The readiness report gives DPN AI and operators one secret-safe view of whether the currently registered connector ecosystem is actually executable. It is derived only from Connector Protocol manifests and transport health state.

It does **not** execute connector actions, contact providers beyond whatever a transport health adapter already performs, decrypt SecretVault values, expose provider response bodies, or authorize mutations.

## Ready criteria

A connector is ready only when all of the following are true:

1. The manifest reports the connector as configured.
2. The connector is enabled.
3. Transport health is `healthy` or `degraded`.

Any missing requirement fails closed and produces a bounded reason code: `not_configured`, `disabled`, or `unhealthy`.

The ecosystem-level `ready` flag is true only when at least one connector exists and every registered connector is ready. An empty ecosystem therefore never reports a misleading green state.

## Approval evidence

The report also lists each connector action whose capability manifest requires explicit approval and returns an aggregate approval-required capability count. This is evidence only. It does not grant, consume, or bypass an approval token.

External HTTP writes, first-party profile installation, and arbitrary MCP tool execution continue to use their existing human-approval boundaries.

## Security properties

- Fail closed when health is unavailable.
- Reject duplicate connector identities across transports.
- Do not execute connector actions during readiness evaluation.
- Do not decrypt or return credentials.
- Do not return provider exception text or response payloads.
- Do not treat an empty connector ecosystem as ready.
- Preserve explicit approval requirements from each capability manifest.

## Verification

`tests/test_dpn_connector_ecosystem_v10.py` covers mixed ready/blocked states, health failure handling, approval-evidence aggregation, and the empty-ecosystem fail-closed case.

`tests/test_dpn_connector_approval_bridge_v10.py` pins `dpn_connector_ecosystem_readiness` to the `connectors` gate with `read` risk so it cannot silently become a mutation surface.
