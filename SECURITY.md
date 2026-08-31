# Security Policy

## Supported Versions

The current `main` branch and current DPN AI v5 release line are the supported development targets.

## Reporting a Security Issue

Do not post API keys, vault keys, tokens, passwords, connector secrets, MCP credentials, private project data, local databases, exploit payloads, or sensitive tool-output data in a normal GitHub issue.

Use GitHub private vulnerability reporting if enabled or an established private DPN Technology security/administrative channel.

Include:
- Affected DPN AI version
- Affected tool/adapter/plugin/connector/model path
- Security impact
- Sanitized reproduction steps
- Whether external systems or secrets may be exposed
- Recommended containment, if known

## Never Commit

- `.env`
- Vault/master keys
- API tokens or passwords
- Live SQLite databases
- Private workspace/project files
- Generated user artifacts containing private data
- MCP or connector credentials
- Browser/desktop session secrets
- Local model/service credentials
- Runtime logs containing sensitive context

## Tool and Capability Security

New tools, plugins, connectors, and MCP integrations must:
- Declare their intended scope
- Validate input
- Respect workspace boundaries
- Use approval gates for high-risk/external actions
- Keep secrets in the encrypted vault
- Produce auditable structured results
- Avoid claiming permissions/capabilities they do not actually have

## Sandbox and External Control

Browser, desktop, shell, network, and code-execution capabilities must preserve configured approval and isolation controls. Changes must not silently weaken tool gates or sandbox restrictions.
