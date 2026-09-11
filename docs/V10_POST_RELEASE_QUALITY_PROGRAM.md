# DPN AI v10 Post-Release Quality Program

## Purpose

This program governs the DPN AI v10 maintenance and refinement sequence beginning with v10.0.1.

The objective is not to add empty feature surface. The objective is to make the existing platform understandable, reliable, consistent, testable, and comfortable to operate before expanding it further.

"100%" in this program means 100% of the defined acceptance gates and audit checklist must pass, with no known release-blocking defects. It does not mean claiming that software can never contain an undiscovered defect.

## Non-Negotiable Product Standard

Every user-facing surface must meet all of the following before a checkpoint can be promoted:

1. Plain-English labels.
2. A user can understand what a control does before changing it.
3. Advanced terminology is either removed from the default flow or explained next to the control.
4. No mojibake, broken encoding, replacement characters, or malformed Unicode.
5. No decorative characters used as a substitute for understandable labels.
6. No permanently obstructive or non-dismissible utility panel.
7. No dead button, dead menu item, inaccessible control, clipped content, hidden required action, or non-scrolling modal.
8. No raw JSON required for an ordinary-user workflow.
9. Dangerous settings clearly describe risk and remain fail-closed.
10. Defaults are safe and useful.
11. Errors explain what happened, what the user can do next, and where technical evidence exists.
12. Version labels are coherent across desktop, API, package, documentation, and release metadata.
13. Existing security, approval, recovery, and evidence gates may not be weakened to make UX easier.
14. All relevant automated tests and release gates pass on the exact checkpoint head.

## Confirmed v10.0.0 Baseline Defects

The v10.0.0 stable baseline contains confirmed user-experience defects that are release-blocking for v10.0.1:

- The desktop UI contains mojibake such as `â€¢`, `â€”`, and `Ã—`.
- Multiple user-facing surfaces contain legacy version terminology such as "WINDOWS DESKTOP PLATFORM v8" and v9-specific injected desktop components even though the application is v10.
- The v9 Live Activity rail is injected into the desktop and its close control only toggles a collapsed state. The rail remains present.
- System Settings exposes specialist implementation concepts directly to ordinary users, including profile-specific model routes as raw JSON.
- Model, provider, planner, worker, reviewer, embedding, compatible endpoint, MCP, Capability Forge, host sandbox, and approval terminology is presented without a consistent beginner explanation.
- The settings screen is one long undifferentiated form rather than a task-oriented configuration experience.
- Several buttons rely on decorative glyphs instead of clear text or labeled controls.
- Correct Unicode bullets and symbols are also widely used as decorative separators. v10.0.1 will default user-facing status text to plain punctuation and words so encoding and font differences cannot corrupt meaning.

These are treated as defects, not style preferences.

---

# Release Sequence

## v10.0.1 - Usability Recovery and Interface Sanitation

Primary goal: make the existing desktop application understandable and clean before deeper optimization.

### Required work

#### A. Encoding and text sanitation
- Audit all desktop user-facing strings for mojibake and malformed Unicode.
- Audit Android user-facing strings for the same class of defects.
- Replace malformed separators and multiplication symbols.
- Prefer plain text separators such as commas, slashes, parentheses, or labeled rows instead of decorative bullets.
- Add an automated source scan that fails CI if known mojibake patterns are introduced.
- Add regression coverage for rendered strings used by key desktop surfaces.

#### B. Remove the Live Activity rail
- Remove the always-injected `v9ActivityRail` from the main desktop.
- Remove its toggle/collapse logic and related CSS.
- Preserve useful mission/approval/automation/connector counts only where they belong in dedicated pages or the dashboard.
- Ensure no blank offset, floating remnant, focus target, keyboard target, or accessibility landmark remains.
- Add a regression test proving the rail is absent.

#### C. Settings redesign
Replace the single expert-oriented settings dump with grouped, task-oriented sections:

- General
- AI Models
- Permissions & Safety
- Web & Browser
- Voice
- Automations
- Connectors
- Files & Workspace
- Advanced

Every setting must have:
- a human-readable name,
- a one-sentence description,
- a recommended/default value where appropriate,
- a consequence/risk explanation for sensitive options,
- validation before save,
- a reset-to-recommended path.

Advanced implementation fields must be hidden behind an explicit Advanced section.

Raw model-route JSON must not be required for normal configuration. Provide a structured route editor with profile, model, add, remove, and reset controls. Raw JSON may remain only as an expert import/export surface if still useful.

#### D. Terminology cleanup
Create one product-language glossary and use it consistently.

Examples:
- "Compatible provider" -> explain as "Another AI server that uses an OpenAI-compatible API".
- "Embedding model" -> explain that it powers search/memory matching and normally should not be changed.
- "Planner / Worker / Reviewer" -> explain their roles and default automatic behavior.
- "MCP" -> show "Tool Server Connections (MCP)" on first use.
- "Capability Forge" -> explain as the controlled local plugin builder/validator.
- "Host sandbox fallback" -> clearly mark as Advanced and explain that it is weaker isolation than Docker.
- "Approval mode" -> replace vague mode names with user-centered descriptions and show exactly what each mode permits.

#### E. Navigation and module explanations
Every primary module must have:
- a one-line purpose statement,
- an empty-state explanation,
- a first action the user can take,
- a Help/What is this? affordance,
- risk messaging if the module can execute or modify data.

Initial modules:
Chat, Missions, Jobs, Knowledge Graph, Sandbox, Capability Forge, MCP/Tool Servers, Approvals, Projects, Automations, Runs/Audit, Snapshots, Files, Memory, Skills/Workflows, Connectors/Secrets, Diagnostics, Settings, Voice.

#### F. Desktop version and legacy-label cleanup
- Remove v8/v9 branding from the v10 user-visible desktop.
- Keep legacy implementation filenames only where changing them would create needless risk.
- User-facing copy must identify the active v10.0.1 checkpoint consistently.
- Audit cache-busting/static asset version strings.

#### G. UX regression suite
Add tests for:
- no known mojibake patterns,
- no Live Activity rail,
- settings sections present,
- normal settings do not require JSON,
- every main module has explanatory copy,
- dangerous controls include risk/help text,
- current version appears correctly,
- modal scrolling and keyboard focus behavior,
- no duplicate navigation targets,
- no missing DOM targets referenced by JavaScript.

### v10.0.1 exit gate
- 100% v10.0.1 UX checklist pass.
- 100% applicable automated tests pass.
- Security/recovery gates remain green.
- No known P0/P1 UX defect.
- No known mojibake in desktop or Android source.
- Exact-head CI evidence recorded.

---

## v10.0.2 - Module Usability and Empty-State Overhaul

Primary goal: make every existing feature discoverable and understandable.

- Walk every module end to end.
- Replace developer-centric empty screens with guided empty states.
- Add descriptions, examples, and safe starter actions.
- Standardize page headers, status blocks, actions, confirmations, and error states.
- Remove duplicate or overlapping controls.
- Verify scrolling, resizing, keyboard use, and low-resolution layouts.
- Add per-module UI contract tests.

Exit gate: every major module can be understood without reading source code or external documentation.

---

## v10.0.3 - Workflow Clarity and Error Recovery

Primary goal: make failures recoverable by a normal user.

- Rewrite errors in plain English.
- Add "What happened" and "What to do next" patterns.
- Preserve detailed technical evidence behind expandable diagnostics.
- Add retry/recover/reset actions only where safe.
- Improve approval explanations.
- Improve mission/job progress presentation.
- Remove vague status language such as "Ready" when a more precise state is available.
- Test failure, timeout, cancellation, unavailable-provider, and permission-denied flows.

Exit gate: every tested failure path provides a clear user action or a clear reason no action is possible.

---

## v10.0.4 - Models, Providers, Voice, and Multimodal Setup

Primary goal: make advanced AI configuration approachable.

- Guided model setup.
- Detect installed/local providers.
- Explain local vs external privacy implications.
- Model health/test button.
- Recommended model badges.
- Voice installation/status guidance.
- Image/vision provider setup guidance.
- PDF/audio/video capability readiness indicators.
- No provider is shown as available unless evidence confirms it.

Exit gate: a first-time user can configure a working model and understand unavailable multimodal capabilities without knowing provider jargon.

---

## v10.0.5 - Tools, Permissions, Connectors, and Safety UX

Primary goal: retain strong security while making controls understandable.

- Redesign permission controls around user intent.
- Show Read / Create / Modify / Delete / Execute impact clearly.
- Explain why approval is required.
- Improve connector setup and test flows.
- Replace secret-template jargon with guided secret fields.
- Clarify MCP/tool server risk.
- Add permission previews before saving.
- Add safe reset to recommended security defaults.
- Verify destructive actions remain approval-controlled.

Exit gate: no security-relevant control depends on unexplained terminology.

---

## v10.0.6 - Projects, Memory, Research, and Knowledge UX

Primary goal: make long-horizon intelligence understandable.

- Project onboarding and scope explanation.
- Memory scope explanations: working, conversation, project, organization, user, procedural, episodic, semantic.
- Provenance/conflict indicators in plain language.
- Research source/evidence presentation overhaul.
- Explain conflict detection and fact-checking outcomes.
- Clear memory delete/disable/scope controls where supported and safe.
- Knowledge indexing progress and troubleshooting.

Exit gate: users can tell what is remembered, where it is scoped, and why a research conclusion is supported.

---

## v10.0.7 - Coding, Browser, Computer, and Mission UX

Primary goal: make autonomous work observable without exposing confusing internals.

- Repository mapping summary.
- Plan/change/test/review/security evidence presentation.
- Clear isolation/workspace boundaries.
- Browser/computer action previews.
- Mission checkpoints and recovery presentation.
- Human-readable CI diagnosis.
- PR-ready evidence summary.
- Clear stop/cancel/retry behavior.

Exit gate: a user can understand what DPN AI intends to change, what it changed, and what evidence proves the result.

---

## v10.0.8 - Artifact Studio and Professional Output Experience

Primary goal: make document/spreadsheet/PDF/presentation generation feel like a finished product.

- Guided artifact templates.
- Output preview/status.
- Validation results in plain English.
- Consistent save/export/open-location actions.
- Explain unsupported provider-dependent operations.
- Improve file naming, destination selection, and overwrite protection.
- Validate DOCX/PDF/XLSX/PPTX output paths and error handling.

Exit gate: professional artifact creation is usable without understanding internal tool names.

---

## v10.0.9 - Full v10.0.x Acceptance and Cleanup

Primary goal: close the first post-release hardening series.

- Complete application-wide UI walk-through.
- Dead-code and stale-label audit.
- Duplicate module/action audit.
- Accessibility audit.
- keyboard/focus audit.
- responsive/layout audit.
- performance smoke test.
- full test/security/recovery/release-gate run.
- documentation reconciliation.
- exact version-surface audit.

Exit gate: no known release-blocking usability, encoding, navigation, explanation, or regression defect.

---

# v10.1.x Series

The v10.1.x series begins only after the v10.0.x usability baseline is clean.

## v10.1.1 - Guided First-Run Experience
- First-launch setup wizard.
- Hardware/provider detection.
- Safe recommended configuration.
- Privacy/local-vs-external explanation.
- Test model, voice, browser, and artifact readiness.
- Skip/return-later support.

## v10.1.2 - Unified Help and Contextual Education
- Searchable in-app help.
- Contextual "What is this?" panels.
- Glossary.
- Examples for every major module.
- Troubleshooting links tied to actual diagnostics.

## v10.1.3 - Personalized Workspace and Layout
- User-selectable dashboard cards.
- Persisted layout preferences.
- Hide unused modules without disabling backend capability.
- Density and readability controls.
- Restore-default-layout support.

## v10.1.4 - Observability and Operations UX
- Human-readable health center.
- Capability readiness matrix.
- Provider/connectivity status.
- Storage/resource usage.
- Actionable warnings.
- Diagnostic export bundle with secret redaction.

## v10.1.5 - Automation and Proactive Intelligence UX
- Guided automation builder.
- Plain-English condition builder.
- Execution preview.
- Approval/risk preview.
- Run history and failure explanation.
- Pause/disable controls that reflect confirmed backend state.

## v10.1.6 - Specialist Agents and Marketplace UX
- Explain each specialist.
- Capability cards.
- Trust/source/version indicators.
- Install/enable/disable/update workflows.
- Approval-controlled promotion.
- No plugin can silently expand permissions.

## v10.1.7 - Performance and Responsiveness
- Desktop interaction latency budgets.
- API latency tracking.
- long-list virtualization/pagination where needed.
- background loading.
- memory/resource regression limits.
- startup and first-response measurements.

## v10.1.8 - Cross-Platform Consistency
- Desktop/Android terminology alignment.
- Shared status meanings.
- Shared approval language.
- Shared version labels.
- mobile clipping/scrolling/accessibility checks.

## v10.1.9 - v10.1.x Acceptance
- Full cross-platform regression.
- usability matrix.
- accessibility matrix.
- security/recovery regression.
- performance budgets.
- documentation and release evidence.

---

# Future v10 Minor-Series Rule

Future v10.2.x, v10.3.x, and later v10 maintenance/minor series must follow the same discipline:

1. define the problem and measurable acceptance gate,
2. inspect the current repository before editing,
3. make the smallest coherent real implementation,
4. add regression coverage,
5. run exact-head validation,
6. preserve fail-closed security,
7. document what changed and why,
8. do not promote a checkpoint with known release-blocking defects.

No work should be moved to v11 merely to avoid finishing the approved v10 quality program.

---

# Application-Wide Audit Matrix

Every release checkpoint must consider these surfaces where applicable:

- desktop shell and navigation
- chat/composer
- settings
- models/providers
- voice
- image/vision/media
- missions
- coding
- research
- browser/computer control
- projects/tasks
- memory/knowledge
- automations
- proactive intelligence
- specialist agents
- capability marketplace/forge
- connectors/secrets
- MCP/tool servers
- approvals
- files/workspace
- snapshots/recovery
- runs/audit
- diagnostics/health
- artifact generation
- Android client
- API error contracts
- installation/upgrade/repair
- packaging/release metadata
- documentation
- accessibility
- performance
- security and approval boundaries

---

# Quality Severity

## P0 - Release stop
Security bypass, destructive action without approval, data loss/corruption, broken startup, unrecoverable upgrade failure.

## P1 - Release stop
Major feature unusable, dead primary navigation, settings cannot be safely understood/saved, malformed user-facing text, persistent obstructive UI, severe clipping/scrolling failure, false success/readiness state.

## P2 - Must normally fix in current series
Confusing terminology, inconsistent states, missing guidance, awkward workflow, poor error recovery, accessibility defect, visual inconsistency.

## P3 - Polish backlog
Minor spacing, copy refinement, non-blocking cosmetic improvement.

v10.0.1 may not ship with known P0 or P1 defects.

---

# v10.0.1 First Implementation Order

1. Add automated mojibake/user-facing-text regression scan.
2. Remove the Live Activity rail and its residual CSS/event wiring.
3. Correct all currently known malformed desktop strings.
4. Remove visible v8/v9 version wording from the v10 desktop.
5. Refactor System Settings into understandable sections.
6. Replace raw normal-user model-route JSON with structured controls.
7. Add contextual explanations for every settings control.
8. Audit all primary module labels and empty states.
9. Add DOM/navigation/settings regression tests.
10. Run full CI, Security Gate v2, Runtime & Recovery Assurance, and exact-head readiness checks.

This order intentionally fixes foundational UI correctness before broader design changes.
