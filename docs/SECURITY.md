# DPN AI v5 Security Guide

## Default boundaries

- The web server binds to `127.0.0.1` by default.
- Remote API requests require `DPN_ACCESS_TOKEN`.
- File tools are confined to the configured workspace.
- Safe mode blocks execution and external/destructive actions.
- Standard mode pauses destructive, external, and desktop actions for approval.
- Autonomous mode uses all explicitly enabled tools; it does not bypass workspace or resource limits.

## Sandboxes

Docker is the only isolation boundary provided by the code sandbox. Network access is rejected. The host fallback is disabled by default and must be treated as ordinary local process execution, not containment.

## MCP and connectors

MCP is disabled by default. New MCP servers have no callable tools. Non-loopback endpoints are disabled unless explicitly enabled. Sensitive environment values use encrypted vault references. Connectors and MCP calls can still reach powerful external systems after approval; restrict credentials and allowed operations at the service itself.

## Capability plugins

Staged plugins are inactive. Promotion and rollback require approval. Existing versions are backed up. Static validation is limited; trusted review remains required because active plugins execute in the DPN AI process.

## Computer control

Browser and desktop adapters are optional and disabled by default. Observe before acting, use Standard approval mode, and do not grant the operating-system account more privileges than necessary.

## Models and prompt injection

Files, webpages, tool output, and MCP responses can contain hostile instructions. Treat retrieved content as data, keep system policy authoritative, use focused tool routing, require approvals for side effects, and verify results independently.

## Backups

Create a verified workspace snapshot before broad modifications. Store important release archives and encrypted-vault backups in a separate protected location. The application cannot recover a disk that has failed without an external copy.