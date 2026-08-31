# Extending DPN AI v5

Prefer extension methods in this order:

1. Existing built-in tool
2. Reusable skill pack
3. Deterministic workflow
4. Approval-controlled HTTP connector
5. Reviewed MCP server and minimum tool allowlist
6. Staged local plugin through Capability Forge
7. Core modification only when the extension APIs cannot satisfy the requirement

A plugin must expose `register(registry)`. Stage and validate it before promotion. Do not place secrets in plugin source; use the encrypted vault. Keep tools narrow, validate inputs, confine file paths, declare risk accurately, produce structured results, and add tests.