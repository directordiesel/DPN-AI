# DPN AI v10 — MCP Connector Protocol Bridge

This checkpoint integrates the existing hardened `MCPBridge` with DPN Connector Protocol instead of introducing another MCP transport or credential path.

## Security model

- Configured MCP servers are discovered from the existing MCP persistence layer.
- Catalog generation does not start MCP server processes or make remote MCP calls.
- Only tools already present in a server's explicit `allowed_tools` list become DPN Connector Protocol capabilities.
- Every MCP tool capability is modeled as write-risk and `approval_required=True`. DPN AI does not infer safety from an MCP tool name or schema because arbitrary MCP tools can have external side effects.
- The public `dpn_connector_mcp_call` tool does not accept an approval boolean. `ToolPermissionRuntime` forces it through the existing ApprovalSecurity inbox even in autonomous / Always Allow modes.
- After ApprovalSecurity releases a single approved invocation, `MCPConnectorProtocolService.approved_call` constructs the internal approved protocol request.
- Immediately before execution, the adapter reloads the live MCP server record and rechecks that the selected tool is still allow-listed. Revoking a tool after approval therefore fails closed.
- The adapter reuses `MCPBridge.call_tool`, preserving the existing deny-by-default allowlist, MCP transport restrictions, executable allowlist, external-host policy, vault-backed secret resolution, and MCP call persistence.
- Connector provenance records provider/server/tool identity but never copies tool arguments into provenance.
- Missing, disabled, or unavailable MCP servers fail closed. Missing optional MCP SDK support reports degraded health rather than fabricated success.

## Protocol mapping

Each configured MCP server is exposed as connector ID `mcp:<server_id>` with:

- `discover / tools` — read-only MCP tool discovery.
- `health / server` — local health/status evidence.
- `update / tool:<allowlisted-tool-name>` — approval-required execution of one explicitly allow-listed MCP tool.

`update` is intentionally used as the generic external-side-effect action. Until DPN AI has provider-specific semantic metadata proving that a tool is read-only, MCP calls are not downgraded to read risk.

## Plugin surface

The v10 connector plugin registers:

- `dpn_connector_mcp_catalog`
- `dpn_connector_mcp_discover`
- `dpn_connector_mcp_call`

The first two are non-destructive discovery operations. `dpn_connector_mcp_call` is registered as destructive risk so existing approval storage, expiration, live-policy revalidation, single-use claim, and replay prevention apply.

## Verification coverage

`tests/test_dpn_mcp_connector_adapter_v10.py` covers capability derivation, approval enforcement, live allowlist revalidation, metadata-only provenance, discovery behavior, secret-redacted manifests, and action/resource confusion.

`tests/test_dpn_connector_approval_bridge_v10.py` additionally verifies that MCP calls remain human-approval gated in autonomous mode, cannot bypass a disabled MCP feature gate, and are registered on the destructive plugin surface.
