# MCP Tool Bridge

The MCP bridge is optional and uses the stable v1 Python SDK constraint in `requirements-mcp.txt`.

## Supported transports

- local stdio processes;
- loopback Streamable HTTP by default;
- non-loopback HTTP only when explicitly enabled by environment policy.

## Trust procedure

1. Configure a server with an empty allowlist.
2. Approve and run discovery.
3. Review tool names, descriptions, schemas, server command or URL, and credential references.
4. Save only the minimum trusted names.
5. Execute calls through the DPN approval policy.
6. Review the local MCP call audit.

Sensitive environment variables must use exact encrypted references such as `{{secret:MCP_TOKEN}}`. The command center never displays secret values.

MCP servers are separate software and may have their own privileges. DPN AI cannot make an unsafe server safe; it limits which configured tools may be invoked and records calls.