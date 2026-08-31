# Contributing to DPN AI

DPN AI is a local-first AI execution platform. Changes should preserve evidence-based behavior, tool boundaries, recoverability, persistent state integrity, and approval controls.

## Preferred Workflow

1. Branch from `main`.
2. Make a focused change.
3. Add/update tests.
4. Run the development test suite.
5. Update version/changelog/architecture/security documentation when behavior changes.
6. Open a pull request and complete the checklist.
7. Merge after CI passes.

## Local Validation

Install development requirements:

```bash
python -m pip install -r requirements-dev.txt
```

Run:

```bash
python -m compileall -q app tests
pytest -q
```

## Extension Order

Prefer:
1. Existing built-in tool
2. Skill pack
3. Deterministic workflow
4. Approval-controlled HTTP connector
5. Reviewed MCP server with minimum allowlist
6. Staged local plugin through Capability Forge
7. Core modification only when necessary

## High-Risk Areas

Extra review is required for:
- Tool policy and approval gates
- Shell/code execution
- Browser/desktop control
- File/workspace boundaries
- Vault encryption
- HTTP connectors
- MCP servers
- Plugins/Capability Forge
- Mission/autonomous execution
- Background jobs/automations
- Model gateway
- Persistence/migrations
- Recovery/checkpoints

## Security

Follow `SECURITY.md`. Never use production secrets or private user/project data as test fixtures.
