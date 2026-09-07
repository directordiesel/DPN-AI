# DPN AI v10.0.0 — Batch 12 Completion Evidence

Batch 12 implements the Persistent Specialist-Agent Organization checkpoint inside the single DPN AI v10.0.0 program.

## Exact verified head

`b9fac9f8f51e3f9a41b3a15cb23449ae9754c4b1`

## Verification

- GitHub-hosted CI passed on Ubuntu and Windows, Python 3.11 and 3.12.
- DPN Security Gate v2 passed.
- Repository Health passed.
- The dedicated Batch 12 specialist release readiness gate passed on Ubuntu/Python 3.11 after the Batch 8–11 gates.
- Windows Desktop Package skipped as expected for this change set.

## Release-readiness evidence

Five mandatory families are enforced at 1.0 success and 1.0 quality:

1. `specialist_persistence_recovery`
2. `specialist_capability_isolation`
3. `specialist_handoff_integrity`
4. `specialist_mission_integration`
5. `specialist_approval_boundary`

Each family maps to immutable exact pytest evidence and is executed by the Batch 12 release CI harness.

## Security conclusions

- Specialist identities are constraints, not security principals.
- Model-visible tools cannot directly execute specialist assignments.
- Host-side execution revalidates active assignment, enabled identity, live allowlist, required-tool coverage, and bound mission state.
- Tool execution delegates only through `ToolRegistry.execute(...)`, preserving ApprovalSecurity and existing tool risk/gate enforcement.
- There is no direct `_invoke()` path, no approval bypass, no autonomous specialist loop, and no destructive repository behavior.
- Capability drift and terminal mission/assignment state fail closed.

Batch 12 is complete for approval-controlled review and remains unmerged.
