# DPN AI v10 Connector Ecosystem Health

This checkpoint adds a unified DPN Connector Protocol inventory and readiness surface across the concrete HTTP and MCP transports already implemented in Batch 6.

## Goals

- Provide one deterministic ecosystem catalog without executing external actions.
- Provide one fail-closed health snapshot for configured connector transports.
- Preserve transport-specific capability declarations and approval requirements.
- Reject duplicate connector identities across transports rather than guessing which provider owns an ID.
- Keep connector configuration, credentials, request bodies, tool arguments, and provider exception details out of ecosystem output.

## Runtime

`app/dpn_connector_ecosystem_v10.py` combines the registries produced by `HTTPConnectorProtocolService` and `MCPConnectorProtocolService`. The ecosystem service does not provide create/update/delete or MCP tool execution. It only reads validated manifests and calls the registry health contract.

The catalog reports connector identity, kind, display name, configured/enabled/local state, protocol version, safe manifest metadata, and declared capabilities. Capability risk and approval requirements are preserved exactly from each concrete adapter.

The health snapshot reports each connector as healthy, degraded, unavailable, or unconfigured. Adapter exceptions are converted by the registry to `unavailable`; raw provider exception text is not returned. `executable_count` includes only configured and enabled connectors whose health is healthy or degraded.

## Tool Surface

The Batch 6 plugin exposes two additional read-only tools:

- `dpn_connector_ecosystem_catalog`
- `dpn_connector_ecosystem_health`

These tools cannot authorize or execute connector writes. Existing HTTP writes and MCP tool calls remain behind the trusted approval boundary.

## Security Properties

1. Duplicate connector IDs across HTTP and MCP fail closed.
2. Inventory does not start MCP servers or perform HTTP requests.
3. Health checks use each protocol registry's existing guarded health behavior.
4. Provider exceptions are not copied into readiness output.
5. No new secret store, network transport, or approval mechanism is introduced.
6. Destructive/high-risk execution remains isolated to the previously approval-gated connector tools.

## Verification

`tests/test_dpn_connector_ecosystem_v10.py` covers multi-transport catalog aggregation, deterministic identity ordering, fail-closed adapter exceptions, disabled connector handling, degraded readiness counting, absence of provider exception leakage, and duplicate-ID rejection.
