# DPN AI v6 Release Readiness

This document is the evidence checklist for promoting the `feature/dpn-ai-advanced-core-v6` branch toward a stable release. It is intentionally stricter than a feature checklist: implemented or configured does not mean runtime-healthy, and a green request response does not replace validation evidence.

## Fixed release gates

All gates must be evidenced for the exact current head before v6 may be considered release-ready:

- CI succeeds.
- DPN Security Gate v2 succeeds.
- Runtime & Recovery Assurance succeeds.
- v6 regression tests succeed.
- No known critical security finding remains unresolved.
- PR #24 remains reviewed as the v6 integration surface.
- README/release documentation matches current behavior and known limitations.
- `main` remains unchanged until an explicitly authorized merge.

Pending, absent, cancelled, unknown, or skipped evidence does not count as passing unless the corresponding gate definition explicitly allows it.

## Capability matrix

The final audit must classify each domain as `available`, `degraded`, `unavailable`, `blocked-by-policy`, or `not-configured`, with observable evidence and remediation where relevant:

- Model providers and intelligent routing
- Core tool registry and focused tool discovery
- Skills and plugin loading
- Coding Agent v6
- Document & Artifact Studio v6
- Image & Vision Studio v6
- Research & Browser Agent v6
- Repository Intelligence v6
- Multimodal/File Intelligence v6
- Long-Term Memory & Persistent Knowledge Graph v6
- Mission Recovery & Self-Evaluation v6
- Automation Composition & Operations Studio v6
- Connector Orchestration & External Systems v6
- Artifact Preview & Capability Experience v6
- Native Vision & Deep Multimodal Reasoning v6
- Browser, desktop, voice, media, sandbox, archive, MCP, connector, vault, persistence, job-supervisor, and recovery foundations

## Integration audit

The final release review must verify handoffs instead of testing each feature only in isolation. At minimum:

1. Universal Creator -> specialist planner selection.
2. Intelligent Model Router -> actually available model/provider, including vision requirements.
3. Specialist execution -> artifact/tool/test evidence.
4. Multimodal ingestion -> exact page/sheet/slide/frame/file provenance.
5. Persistent memory -> project scope, provenance, confidence, freshness, contradiction handling.
6. Mission recovery -> verified checkpoint resume and bounded repair.
7. Automation -> live authorization and resumable state.
8. Connector orchestration -> vault references, allowlists, idempotency, readback, reconciliation.
9. Artifact preview -> structural validation separated from visual-fidelity claims.
10. Native vision -> real visual input, actual vision model, observation/inference separation, bounded cross-checking.

## Security invariants

Release work must not weaken these controls to obtain a green build:

- Workspace path confinement and symlink protections.
- Safe command allowlists and blocked destructive/system commands.
- Package-install restrictions.
- Sensitive environment stripping.
- Approval gates and live permission re-checks.
- Browser private-network restrictions and disabled downloads where configured.
- Connector host/method confinement and redirect/host-escape protections.
- MCP discovery-before-allowlisting and deny-by-default tool calls.
- Vault references for secrets; no plaintext credential persistence.
- External model/connector permissions remain opt-in.
- Archive/media/input bounds remain enforced.
- Operator cancellation remains terminal user intent; app shutdown remains resumable pause.
- No test deletion, assertion relaxation, or security bypass solely to make validation pass.

## Final release evidence

Before changing PR #24 from draft, record:

- Base SHA
- Head SHA
- PR state and mergeability
- Changed-file/commit totals
- CI run ID/result
- DPN Security Gate v2 run ID/result
- Runtime & Recovery Assurance run ID/result
- Focused regression results for all v6 packages
- Known degraded/optional capabilities and why
- Known blockers and exact remediation
- Documentation status
- Release-readiness decision produced by `evaluate_v6_release_gates`

## Merge policy

Passing all release gates means the branch may be prepared for review/merge. It does **not** authorize an automatic merge. Stable merge requires explicit user authorization.
