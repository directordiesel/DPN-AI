# DPN AI Roadmap

This roadmap describes the current engineering direction. It is outcome-based and does not promise fixed delivery dates.

| Horizon | Direction |
| --- | --- |
| **Now** | Stabilize v5.0.7 adaptive UI, Sentinel HD voice, mission execution, document editing, recovery, and tool-policy behavior. |
| **Next** | Improve evaluation quality, sandbox isolation, model routing, connector/MCP governance, mission observability, and capability installation. |
| **Later** | Expand multimodal workflows, durable automation, distributed model/tool backends, richer project collaboration, and measurable autonomous reliability. |

## Engineering Priorities
- Preserve working behavior while modernizing architecture.
- Add regression coverage before removing compatibility code.
- Keep secrets, live operational data, generated databases, backups, and private keys out of Git.
- Prefer observable and recoverable workflows over silent failure.
- Keep production prerequisites separate from demo/default configuration.

## Release Discipline
1. Update version metadata.
2. Update README version/status badges.
3. Update changelog or release notes.
4. Add regression/smoke coverage for changed subsystems.
5. Update security/deployment documentation when operational behavior changes.
