# DPN AI v10.0.0 — Durable Proactive Condition Lifecycle

## Purpose

Batch 11 now persists proactive condition definitions across restarts without introducing a second scheduler or an execution bypass. The lifecycle layer owns definition state only. Existing host/background loops may call its bounded `evaluate_due()` entry point, and any resulting proposal remains non-executable until it later re-enters `ToolRegistry.execute()` and `ApprovalSecurity` through the existing internal dispatcher.

## Persistent definition contract

`app/proactive_lifecycle_v10.py` stores schema-versioned condition definitions in `proactive_v10_definitions.json` using atomic replacement. Each definition records:

- condition ID;
- host-registered source ID;
- bounded comparison operator and threshold;
- target tool and finite JSON arguments;
- evaluation interval;
- proposal cooldown;
- edge-trigger behavior;
- enabled/disabled state;
- created/updated timestamps;
- next due timestamp.

New definitions are always disabled. Registration cannot create an immediately active watcher. Enabling is a separate lifecycle mutation.

## Scheduler boundary

The lifecycle does **not** own a timer thread, event loop, cron system, or autonomous process. `evaluate_due()` is a bounded host-callable function. This keeps DPN AI's existing automation/background-job architecture authoritative and avoids duplicate scheduling systems.

Limits:

- at most 256 persistent definitions;
- evaluation interval from 30 seconds through 24 hours;
- at most 64 due evaluations per call;
- existing condition cooldown remains bounded by the condition engine;
- disabled definitions never collect source evidence.

## Trusted source boundary

Definitions may reference only source IDs already registered by the host in `ProactiveSourceRegistry`. The lifecycle file cannot create a trusted source, alter a source freshness contract, or supply a `trusted_for_dispatch` bit.

At evaluation time the source registry collects fresh evidence and the existing `ProactiveConditionEngine` binds source/evidence digests into any proposal.

## Proposal and dispatch boundary

Due evaluation can:

1. collect trusted evidence;
2. evaluate a condition;
3. create a non-executable proposal;
4. place that proposal into the host-owned cache.

Due evaluation cannot:

- dispatch the target tool;
- provide execution permissions;
- approve an action;
- invoke `ToolRegistry._invoke()`;
- create a trusted source;
- override risk/gate metadata.

The internal dispatcher remains a separate later stage and must re-enter `ToolRegistry.execute()` / `ApprovalSecurity`.

## Recovery and corruption behavior

Lifecycle state is fail-closed. Invalid JSON, invalid schema, definition identity mismatch, invalid persisted bounds, or more than the maximum number of definitions blocks lifecycle operations instead of silently resetting state.

A failed source/engine evaluation is recorded in the returned run result and rescheduled for the definition's next bounded interval; it is not silently promoted to success and no proposal is cached from that failed evaluation.

## Tool surface

Model-visible tools added in this checkpoint:

- `list_proactive_conditions_v10` — read-only list;
- `register_proactive_condition_v10` — persists a disabled definition;
- `set_proactive_condition_enabled_v10` — toggles lifecycle state without evaluating or dispatching.

The actual due-evaluation bridge is attached internally as `registry.evaluate_due_proactive_conditions_v10` and is intentionally not model-visible.

## Verification

Regression coverage is in:

- `tests/test_proactive_lifecycle_v10.py`;
- `tests/test_proactive_plugin_integration_v10.py`.

Coverage includes persistence, disabled-by-default behavior, source allowlisting, interval bounds, due-time suppression, corrupt-state rejection, proposal caching, approval metadata preservation, and proof that lifecycle evaluation performs no ToolRegistry execution.
