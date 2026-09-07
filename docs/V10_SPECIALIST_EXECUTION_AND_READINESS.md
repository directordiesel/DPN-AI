# DPN AI v10.0.0 — Specialist Execution and Release Readiness

## Purpose

Batch 12 extends the persistent specialist-agent organization with a capability-scoped bridge into the existing DPN AI execution authority. It does **not** add a second tool executor, security principal, mission runtime, or model loop.

## Execution architecture

`SpecialistExecutionFacade` accepts a host-selected assignment, tool name, arguments, and host-resolved permissions. Before execution it reloads the live assignment context from `SpecialistOrganization` and verifies:

- the assignment identity matches the requested assignment;
- the assignment is still active;
- the assigned specialist is still enabled;
- the organization context remains explicitly non-authorizing;
- the requested tool is present in the specialist's current live allowlist;
- all assignment-required tools remain inside that live allowlist;
- a bound mission still exists and is non-terminal.

Only after those checks pass does the facade call the existing `ToolRegistry.execute(name, arguments, permissions)` path. This preserves current `ApprovalSecurity`, permission gates, connector restrictions, command restrictions, destructive-action approval behavior, audit logging, and tool-specific policy.

The specialist layer never calls `ToolRegistry._invoke()` directly and never manufactures an approval token or elevated permission set.

## Model-visible boundary

There is intentionally no model-visible `execute_specialist_*` tool. The plugin exposes organization management and inspection surfaces, while `registry.execute_specialist_assignment_v10(...)` exists only as a host-side orchestration bridge.

A specialist profile is therefore a capability constraint, not a new authorization identity.

## Mission integration

Assignments may bind to existing long-horizon missions. Execution checks the mission again at dispatch time. Missing, completed, cancelled, or failed missions block specialist execution before a tool call is attempted.

The specialist subsystem does not start, resume, checkpoint, cancel, or otherwise mutate the mission runtime by itself.

## Approval behavior

External, execute, destructive, connector-gated, or otherwise approval-controlled tools continue through normal ToolRegistry execution. If ToolRegistry returns an approval-required result, the specialist execution receipt preserves that state and reports `execution_authorized_by_specialist=false`.

## Batch 12 benchmark gate

The release gate requires one exact executed pytest case for each mandatory family:

1. `specialist_persistence_recovery`
2. `specialist_capability_isolation`
3. `specialist_handoff_integrity`
4. `specialist_mission_integration`
5. `specialist_approval_boundary`

All five families require 1.0 success and 1.0 quality. Missing or failed mandatory test evidence fails closed.

The immutable release manifest is defined in `app/specialist_release_audit_v10.py`; the executable CI harness is `app/specialist_release_ci_v10.py`; and GitHub-hosted CI invokes `.github/scripts/specialist_release_readiness_v10.py` on Ubuntu/Python 3.11.

## Security invariants

- No specialist-derived privilege escalation.
- No direct `_invoke()` bypass.
- No model-visible specialist execution tool.
- No execution from disabled or terminal assignments.
- No execution outside the live specialist allowlist.
- No silent continuation after mission or capability drift.
- No automatic approval of risky operations.
- No destructive repository action introduced by Batch 12.
