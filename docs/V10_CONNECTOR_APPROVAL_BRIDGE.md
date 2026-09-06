# DPN AI v10 Connector Approval Bridge

## Purpose

Batch 6 exposes DPN Connector Protocol reads and writes through the existing DPN AI tool runtime without creating a parallel authorization system. External writes remain fail-closed and require a human approval even when the runtime is configured for autonomous execution or a broader permission policy would otherwise allow the tool.

## Registered tools

- `dpn_connector_catalog` lists redacted protocol manifests and declared capabilities.
- `dpn_connector_read` performs bounded read/search operations through the hardened `ConnectorHub` transport.
- `dpn_connector_write` performs only `create`, `update`, or `delete` protocol actions and is registered with the `connectors` gate and destructive tool risk.

## Approval boundary

`ToolPermissionRuntime` contains a dedicated `connector_write_boundary` rule for `dpn_connector_write`. If the connectors feature gate is disabled, execution is denied. If the gate is enabled and the surrounding policy would allow execution, the decision is narrowed to `ASK_EVERY_TIME` rather than widened to autonomous execution.

The existing `ApprovalSecurity` runtime then owns the deferred execution lifecycle:

1. The exact write arguments are encrypted in `SecretVault`; SQLite stores only a sanitized preview.
2. The approval expires after 24 hours.
3. Live feature permissions and tool risk are revalidated immediately before execution.
4. The approval row is atomically claimed from `approved` to `executing`, making execution single-use.
5. Interrupted executions are marked failed and are never automatically replayed.
6. The encrypted deferred payload is deleted after terminal execution.

The protocol service sets its internal `approval_granted` flag only inside the registered write implementation after the core tool approval boundary releases the invocation. It is not accepted as a public tool argument.

## Transport and least privilege

The write bridge does not create another HTTP client. `HTTPConnectorProtocolService` uses `DPNConnectorRegistry`, which invokes `HTTPConnectorProtocolAdapter`, which in turn calls the existing `ConnectorHub`. Existing host/method allowlists, SSRF checks, embedded-credential rejection, encrypted secret resolution, redirect refusal, timeout bounds, and response limits therefore remain in force.

Protocol action and HTTP method must also agree:

- `create` -> `POST`
- `update` -> `PUT` or `PATCH`
- `delete` -> `DELETE`

The connector manifest must declare the requested action. A connector configured only for GET cannot gain write authority through the protocol bridge.

## Audit and secret handling

Protocol audit events contain connector ID, protocol action, resource label, HTTP method, status code, and success state. Request bodies, query values, response bodies, headers, vault templates, and plaintext secrets are excluded from protocol audit metadata.

## Acceptance requirements

Batch 6 must keep regression coverage proving that autonomous mode cannot bypass the human approval rule, a disabled connector gate cannot be bypassed, read actions cannot enter the write surface, action/method confusion is rejected before network execution, and plugin registration preserves the destructive risk classification.
