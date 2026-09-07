# DPN AI v10.0.0 — Persistent Specialist-Agent Organization

## Checkpoint

This document describes the first Batch 12 checkpoint in the single DPN AI v10.0.0 Autonomous Intelligence Platform program. It introduces a durable organizational control plane for specialist identities, capability boundaries, assignments, and handoffs while deliberately reusing the existing agent, long-horizon mission, ToolRegistry, and approval/security architecture.

## Design goal

Specialists are persistent organizational identities, not independent security principals and not a second execution engine. A specialist profile describes what kind of work an identity is intended to handle and which already-registered DPN AI tools may be considered in its assignment context. The organization layer itself never calls those tools.

The first checkpoint supports:

- bounded persistent specialist profiles;
- disabled-by-default registration;
- capability tags and exact live ToolRegistry allowlists;
- durable mission-linked or standalone assignments;
- required-tool coverage checks before assignment;
- non-destructive specialist-to-specialist handoff lineage;
- SHA-256 handoff context digests instead of raw context persistence;
- terminal assignment protection;
- live tool-catalog drift detection;
- atomic state replacement and fail-closed corrupt-state handling.

## Existing architecture reused

`LongHorizonMissionRuntime` already defines a `MissionCheckpointStore` boundary with `get_mission()` and durable recovery semantics. Specialist assignments use the repository's existing mission lookup only to verify that a referenced mission exists. The specialist layer does not start, resume, repair, stop, or checkpoint missions.

`ToolRegistry` already owns the authoritative catalog of registered tool names, descriptions, risk classes, and gates. A specialist's `allowed_tools` must exist in that live catalog when the profile is created. Assignment-required tools must both exist in the live catalog and be a subset of the assigned specialist's allowlist.

`ApprovalSecurity` and `ToolRegistry.execute()` remain the authority for any future execution. The specialist organization does not call `_invoke()`, `execute()`, a model gateway, a connector, a shell, a browser action, or a mission runner.

## Persistence and bounds

The organization file uses schema version 1 and atomic temporary-file replacement. The runtime rejects unreadable JSON, unsupported schemas, duplicate IDs, assignments that reference missing specialists, handoffs that reference missing assignments/specialists, invalid lifecycle states, and impossible handoff counts.

Current hard bounds are:

- 128 specialist identities;
- 2,048 assignments;
- 16 handoffs per assignment;
- 64 allowed/required tools per relevant record;
- 32 capability tags per specialist.

These bounds protect the control plane from unbounded model-generated state.

## Specialist lifecycle

New identities are always `enabled=false`. Enabling an identity changes organization state only; it grants no operating-system, connector, shell, network, model, or ToolRegistry permission.

An assignment can be `pending`, `active`, `handed_off`, `completed`, or `cancelled`. Completed/cancelled assignments are terminal and cannot be reopened. Handoffs require the target specialist to be enabled and to cover every required tool on the existing assignment.

## Handoff integrity

A handoff produces a receipt containing:

- assignment ID;
- source specialist ID;
- target specialist ID;
- bounded reason;
- SHA-256 digest of supplied context;
- timestamp.

The raw handoff context is not written to the specialist organization state file. This reduces accidental duplication of mission, user, research, or sensitive context while still giving later integration layers an integrity reference.

## Governed ToolRegistry surface

The plugin exposes read-only status/list/context-inspection tools and local-state write tools for registration, enable/disable, assignment, handoff, and assignment lifecycle changes. Every write result explicitly reports that no execution was performed.

An internal host bridge, `resolve_specialist_assignment_v10`, returns a validated assignment context with the current live allowed-tool catalog and `execution_authorized=false`. Later checkpoints may use that context to scope existing agent/mission execution, but execution must still enter the repository's established permission and approval boundaries.

## Security invariants

This checkpoint intentionally does **not** add:

- specialist model invocation;
- autonomous specialist loops or threads;
- direct ToolRegistry invocation;
- permission inheritance from a specialist profile;
- approval bypass or self-authorization;
- mission resume/start side effects;
- raw handoff-context persistence;
- automatic enabling of newly registered specialists.

If live tool catalog entries disappear after an assignment was created, assignment context resolution fails closed with tool-boundary drift rather than silently broadening or rewriting the profile.

## Verification

Regression coverage generates persistent organization state and verifies restart recovery, disabled-by-default identities, unknown-tool rejection, mission existence checks, required-tool coverage, handoff lineage, raw-context non-persistence, terminal-state protection, corrupt-state rejection, duplicate-ID rejection, catalog drift detection, plugin risk classifications, and the absence of an execution tool.

## Next checkpoint

After exact-head CI and security validation, Batch 12 should integrate specialist assignment context into existing mission/agent orchestration without creating a competing execution path. That integration must inject only the validated specialist scope, preserve ToolRegistry/ApprovalSecurity enforcement, support durable workload ownership/recovery, and then add benchmark/release evidence for organizational persistence, capability isolation, handoff integrity, mission integration, and approval-boundary preservation.
