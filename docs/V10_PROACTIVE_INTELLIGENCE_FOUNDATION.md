# DPN AI v10.0.0 — Proactive Intelligence Foundation

## Checkpoint

Batch 11 begins the approved **Proactive Intelligence + Condition-Driven Operations** scope inside the single v10.0.0 program.

This checkpoint intentionally separates **condition evaluation** from **action dispatch**. The proactive runtime may observe a supplied scalar value, determine whether a bounded condition is active, record a checkpoint, and return an action proposal. It has no callable dispatch dependency and cannot execute the proposed tool.

## Core implementation

`app/proactive_intelligence_v10.py` provides:

- bounded `ConditionSpec` contracts;
- deterministic `eq`, `ne`, `gt`, `gte`, `lt`, and `lte` evaluation;
- finite-number enforcement for ordered comparisons;
- persistent condition checkpoints with atomic replacement;
- edge-trigger suppression to prevent repeated firing while a condition remains active;
- cooldown suppression for intentionally recurring conditions;
- SHA-256 observation evidence;
- target-tool metadata lookup from the current ToolRegistry catalog;
- non-executable `ActionProposal` receipts carrying the target tool's risk and permission gate;
- fail-closed behavior for corrupt state, unknown tools, unsupported risk classes, malformed JSON arguments, invalid timestamps, and unsafe comparison types.

`plugins/proactive_intelligence_v10.py` exposes two governed tools:

- `proactive_v10_status` — read-only status;
- `evaluate_proactive_condition` — writes only the bounded proactive checkpoint and may return a proposal, but never dispatches it.

## Security boundary

The proactive engine does **not** receive the ToolRegistry call/execute function. It receives only a catalog snapshot. Therefore a model-visible condition cannot turn evaluation into execution.

Every proposal includes:

- tool name;
- copied bounded arguments;
- current registry risk classification;
- current registry permission gate;
- `approval_required` for execute/external/destructive targets;
- `execution_authorized = false` unconditionally.

The existing ToolRegistry and ApprovalSecurity remain authoritative for any future dispatch layer. A later Batch 11 checkpoint may connect proposal dispatch only by re-entering those existing boundaries; it must not add a bypass or secondary approval system.

## Reliability behavior

Conditions default to edge-triggered operation. Once an active condition has proposed an action, repeated matching observations are suppressed until the condition resets. Non-edge recurring conditions are protected by a configurable bounded cooldown.

Persistent state is schema-versioned and atomically replaced. Unreadable or invalid state blocks evaluation instead of silently resetting history, because silent reset could duplicate high-impact proposals.

## Verification

`tests/test_proactive_intelligence_v10.py` covers:

- external-action proposals preserving connector approval metadata;
- destructive-action proposals remaining non-executable;
- edge-trigger reset/retrigger behavior;
- cooldown suppression;
- unknown target tools failing closed;
- corrupt persistent state failing closed;
- invalid ordered comparisons failing closed;
- non-matching observations producing checkpoints without proposals.

## Remaining Batch 11 work

- trusted condition-source adapters and freshness/provenance contracts;
- persistent condition definitions and lifecycle management;
- approval-preserving proposal dispatch through the existing ToolRegistry/ApprovalSecurity path;
- retry/backoff/idempotency and duplicate-action receipts;
- condition-driven mission/connector integration;
- benchmark families and exact release-readiness evidence;
- final security audit and tracker closure.
