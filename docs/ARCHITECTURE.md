# DPN AI v5 Architecture

## Request path

1. The API receives a Direct, Mission, Workflow, Automation, Voice, or Background Job request.
2. The cognitive kernel derives a goal contract.
3. Specialist routing selects a profile and a focused initial tool set.
4. Relevant conversation, project, semantic, indexed-document, and knowledge-graph context is assembled.
5. The model can call focused tools or discover additional tools.
6. Tool policy checks gates, approval mode, risk, workspace boundaries, and resource limits.
7. Results, traces, artifacts, and audit events are persisted.

## Mission path

1. Contract derivation
2. Planner model or deterministic fallback plan
3. Plan normalization and dependency validation
4. Persistent mission and step creation
5. Specialist execution with retry limits
6. Checkpoint after each meaningful state
7. Deterministic evidence verifier
8. Optional repair operation
9. Independent review perspectives
10. Weighted consensus and final mission record

## Persistence

SQLite stores conversations, messages, memory, indexed knowledge, projects, tasks, runs, approvals, automations, workflows, missions, steps, contracts, graph data, checkpoints, evaluations, jobs, MCP servers, and MCP call records. Secrets remain in the encrypted local vault rather than SQLite.

## Extension layers

- Built-in Python tools
- Reusable JSON skill packs
- Deterministic workflows
- Trusted local plugins loaded at restart
- Approval-controlled HTTP connectors
- Optional MCP servers with per-server allowlists
- Optional browser, desktop, voice, media, and ComfyUI adapters

## Failure model

DPN AI distinguishes model claims from evidence. Failures are persisted, jobs can be retried, missions retain attempts and checkpoints, workspace snapshots provide file recovery, and plugin replacements preserve rollback copies.