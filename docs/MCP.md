# MCP Tool Bridge

The MCP bridge is optional and uses the stable v1 Python SDK constraint in `requirements-mcp.txt`.

## Supported transports

- local stdio processes launched only through a small allowlist of runtime executables;
- loopback Streamable HTTP by default;
- non-loopback HTTP only when explicitly enabled by environment policy.

## Trust procedure

1. Configure a server with an empty allowlist.
2. Approve and run discovery.
3. Review tool names, descriptions, schemas, server command or URL, and credential references.
4. Save only the minimum trusted names.
5. Execute calls through the DPN approval policy.
6. Review the local MCP call audit.

## Execution security

Stdio MCP servers must use a bare allow-listed runtime executable name rather than an arbitrary executable path. Shells, package runners such as `npx`, inline Python (`-c` / `-m`), and inline JavaScript evaluation are rejected. Before launch, the executable is resolved through the host PATH and the child process receives a minimal environment instead of inheriting the full DPN AI process environment.

Sensitive environment variables must use exact encrypted references such as `{{secret:MCP_TOKEN}}`. Environment variable names are validated before configuration is saved, and configured values remain redacted in the command center.

HTTP MCP endpoints reject embedded URL credentials, query strings, fragments, unresolved hosts, unspecified addresses, multicast/reserved destinations, and non-loopback targets unless external MCP access has been explicitly enabled. The stored endpoint is revalidated again when a session starts so a previously saved configuration cannot bypass the current network policy.

MCP servers are separate software and may have their own privileges. DPN AI cannot make an unsafe server safe; it limits which configured tools may be invoked, reduces subprocess/environment exposure, enforces transport policy, and records calls.